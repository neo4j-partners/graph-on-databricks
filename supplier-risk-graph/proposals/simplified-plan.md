# Simplified plan: Story 1

> **The graph finds the attribution. The lakehouse computes the number.**

`CONTRACT.md` in this directory is the authority. It holds the claim, the two-claim rule, the two run
definitions, the three legs, the five beats, the verbatim questions, the build-time asserts, the
banned list, and the reseed-invariance rule. This document is the working detail behind it: how each
of those gets built, in what order, and what is already known.

**Nothing settled in the contract is restated here.** An earlier draft of this plan re-told seven
contract sections in its own words, which gave every rule two copies that had to be edited in
lockstep. They drifted. Where you want the rule, read the contract. Where you want the method, read
this.

| For | Read |
|---|---|
| The claim, and what it is not | Contract, section 1 |
| The two-claim rule | Contract, section 2 |
| Run A and Run B, and the fairness rule | Contract, section 3 |
| The three legs | Contract, section 4 |
| The five beats and the frozen questions | Contract, sections 5 and 6 |
| What the build asserts | Contract, section 7 |
| What is banned and what is out of scope | Contract, section 8 |
| Reseed invariance | Contract, section 9 |

---

## The plan in plain terms

A scan layer for orientation, added because this document is dense by design. Nothing in this
section is normative. It deliberately paraphrases, so if it ever disagrees with the contract or
with a detailed section below, the summary is the thing that is wrong.

**The demo, explained simply.** A company buys glass bottles from several suppliers and believes
that supply is diversified. Every one of those suppliers, somewhere up the chain, buys from the
same furnace. Counting suppliers says safe. Following the supply paths says the company is one
furnace away from stopped shipments. The demo asks the same questions of two systems. Run A is
Genie over the lakehouse, and it answers fluently from column names. Run B adds a knowledge graph
holding the company's own written definitions. The point is never that Run A is wrong. The point
is that Run A's answer is anchored to nothing, while Run B's answer is anchored to a definition a
risk committee wrote down and can act on.

**What is broken today, and the fix for each.**

- The furnace, Cascade, sells directly to the bottle makers, so a connection count finds it and
  there is nothing to discover. The fix moves it one tier back, behind sub-tier glass vendors, so
  the dependency is real but visible only to a traversal.
- The governed exposure measure counts every reachable business unit, so it sweeps up the whole
  company and is useless as a number. The fix counts only supply paths that carry the commodity at
  risk, which makes one unit genuinely sole-sourced and the others genuinely protected.
- Several asserts encode the story's outcome rather than the topology's structure, which is the
  fitted-data failure this project keeps repeating. The fix asserts structure and reads every
  outcome from the build output.

**Where the work stands.** Status lives in each phase's opening line; this table mirrors it and is
updated in the same edit.

| Phase | Status | Purpose |
|---|---|---|
| Phase 0, the Run A probe | Complete | Measure Genie's actual reflexes before building anything |
| Phase 1, the governed wording | Complete, one alignment edit open | The four governed texts, approved and landed |
| Phase 2, the guards | In progress | Every check written and proven green against the current build, plus the Run B routing probe |
| Phase 2.5, the rebuild | Not started | The topology, the GDS rework, and the regenerate loop |
| Phase 3, the re-probe | Not started | Ask everything again on rebuilt data and write the beats from transcripts |
| Phase 4, the docs | Not started | Bring every document, diagram, and the Genie space in line with the transcripts |

---

## What the probe established

*In short: measured facts, not expectations. Genie never walked past one hop or wrote a recursive
CTE on any probed question, the dangerous phrasings are identified, and no answer cited a governed
definition.*

`probe-run-a.md` holds the transcripts, the generated SQL, and the full findings from both halves of
the Run A probe: a four-question reflex probe and a five-run spread measurement on the frozen Beat 1
question, both complete 2026-07-19 against space_id `01f17a8bf82813d38c45162703c92a01`, neither
touching the repo. Read the findings there. Repeated here is only what the rest of this plan leans on,
and all of it is established fact rather than expectation.

- **The one-hop ceiling.** Genie never wrote a recursive CTE and never walked past one hop, nine times
  out of nine across both halves, including on a question phrased with the words "depend on." This is
  the actual last line of defense for the demo, not the degree constraint.
- **The danger words are "depend on" and "common upstream," not "point of failure."** Given the phrase
  "common upstream supplier," Genie wrote a correct convergence query on the first try, with strict
  all-of-them semantics and no hints. Beat 1 stays frozen at the diversification-only phrasing for
  that reason.
- **The connection-count guarantee is not load-bearing for any probed question,** because Genie does
  not count connections. Keep the assert, it is cheap and reflexes shift with model updates, but stop
  framing it as the last line of defense.
- **Claim A held five for five, and claim B is confirmed without being certain.** Five runs of the
  same question produced four distinct queries and verdicts spanning the full range, with two runs
  identical to each other. No run cited a governed definition. The identical pair is why B stays B.
- **Two items this plan previously listed as outstanding work are already done.** The `upload.py`
  `supply_relationships` table comment is already the neutral version, and no Genie space example SQL
  touches that table. Both become re-verify-after-rebuild items rather than work items.

**The probe measures reflex, not the final answer.** The current topology has Cascade selling directly
to the tier-1 bottle makers, so every Cascade hit in the probe is one hop away. The query shapes carry
over to the rebuilt topology. The specific answers do not, which is why the re-probe phase exists.

---

## The hidden choke point

*In short: Cascade moves one tier back, feeding sub-tier vendors who feed the tier-1 bottle makers.
Few connections, many paths, and it is not true of the data today.*

A choke point that a connection count already names is not hidden, and there is no discovery step to
demonstrate. So the topology requirement is this: **a connection count must not name Cascade.**

That is not a plant. It is the definition of a hidden choke point. Cascade sits one tier back from the
bottle makers, feeding a small set of sub-tier vendors who feed the tier-1 suppliers. Few connections,
many paths through it. That is the structural-hole case, which is exactly where betweenness and degree
diverge and exactly what a real supply chain looks like.

The requirement is built into the topology, asserted at build time, and stated in the open. It is met
structurally rather than by inflating a bystander's numbers.

**It is not true today.** Cascade currently sells directly to all five tier-1 bottle makers, in the
bridge-linking block of `make_supply_relationships`, which is most of its degree. The rebuild moves it
back one tier.

## Where the difference comes from, leg by leg

*In short: the graph grounds the answer three ways. The definition leg is guaranteed by
construction. Discovery and explanation are about what each engine reaches for naturally, and only
the first cannot fail.*

**Leg 1, definition.** Genie Agent on the lakehouse does not know what a Critical Supplier is, that a
Supply Exposure measure exists, or what THR-03 governs. There is no table it could read to find out,
because the definition was never written down anywhere the lakehouse can see. The graph side has the
terms, rules, thresholds, and metrics, so it states the finding in governed language a risk committee
recognizes. This is the customer's EDM point and it is the claim that cannot fail.

**Leg 2, discovery.** Betweenness weights a supplier by how many multi-tier supply paths route through
it, which is what procurement means when it asks about a choke point. Nobody staffs an analyst to
hand-write Brandes as a recursive CTE. The algorithm is a named, standard, off-the-shelf answer to a
question procurement already asks. We do not need the graph ranking and any SQL aggregate to disagree
in general and we do not assert that they must. The one constraint is the hidden choke point
requirement above.

**Leg 3, explanation.** Genie has the supply edges as rows and no traversal. The probe shows it
answers supply questions at one hop even when the wording invites a chain. Said plainly: once someone
knows to start from the tier-1 suppliers, "which supplier feeds all of these" is a single join, and
Genie can get there. Convergence is cheap in SQL once you know what to converge on. The graph-native
step is the one before it, which is leg 2.

**Expression, not theoretical capability.** Legs 2 and 3 are about what each engine reaches for
naturally, not about what is computable. Recursive CTEs can walk the chain. The claim is that Genie
Agent does not spontaneously write one, that nobody writes Brandes by hand, and that no column governs
what "critical" means.

## The division of labor

*In short: the graph decides which business units are exposed, the lakehouse computes the revenue,
and saying so out loud is what settles the fairness question.*

The graph is not a BI engine and the demo never implies it is. Revenue arithmetic belongs in the
lakehouse, and conceding that makes the demo more credible: the moment the graph appears to be
computing euros, a savvy room asks why you would sum revenue in Neo4j, and they would be right.

It also settles the fairness question for good. The figure in Beat 4 is the lakehouse's figure,
computed by the lakehouse, from a table both runs could read. Nothing was withheld and nothing was
special-cased. The only difference is that one run knew which number to ask for.

## The load-bearing fix: supply paths carry a commodity

*In short: a supply path counts as a dependency only if every supplier on it trades in the
commodity at risk. That one predicate rescues the exposure measure, constrains the rebuild, and
gets its own guard extension.*

Today Supply Exposure is defined as every business unit reached by the supplier's multi-tier
`SUPPLIES` paths. That is unfiltered reachability, and it escapes through suppliers that carry nothing
relevant: warehousing, labels, consulting, ingredients. The measure sweeps up the entire company and
is therefore useless as a scoped number.

**A path counts as a dependency only if it carries the material at risk.** Subcategory already carries
everything needed for this, so it requires no new columns.

**How a path carries a commodity, decided.** `supply_relationships` holds `fromSupplierId` and
`toSupplierId` and nothing else, and subcategory lives on the supplier row. So the commodity test is a
predicate over the nodes on the path, not over the edges: a path is commodity-carrying when every
supplier on it trades in that commodity. Contract section 7 already uses the phrase
"commodity-carrying paths," and this is what it means.

The two alternatives are worse and are recorded so they are not re-proposed. A `commodity` column on
the supply edges hands Run A the convergence query almost for free, which weakens leg 3 further than
the honest caveat in contract section 4 already concedes. Testing only the endpoints is the exact bug
`archive/fix-the-arc.md` diagnosed, where a warehousing vendor in the middle counts as a glass
dependency and the measure sweeps up the company.

**"Trades in that commodity" is a set test, not subcategory equality.** Cascade is raw glass and the
tier-1s are glass bottles, so equality would break the chain at its first hop. A commodity resolves to
a set of subcategories, and glass covers the raw end through the finished bottle. That mapping is an
authored judgment, not instance data, so it lives in the knowledge layer: a constant in the generator
that the build asserts read, and the same set that the Beat 3 traversal filters on. No new node label,
so the ban on those is not reopened.

**Run A gets the values and never the grouping, and this one is mechanically checkable.** The
subcategory values are instance data in Unity Catalog and Run A has always seen them, which the
fairness rule requires. The grouping, meaning the judgment that raw glass and the tiers above it are
one commodity, is exactly the shape of a hint even though it contains no governed identifier and would
pass the vocabulary guard as written. So extend the guard: fail if any table comment, column comment,
or Genie space instruction enumerates two or more members of a single commodity's subcategory set.
Unlike a general paraphrase this is a real check rather than an editorial hope, and it costs nothing
now that the guard already runs standalone in pre-flight.

**This is a constraint on the rebuild, not just on the wording.** Every sub-tier vendor between
Cascade and the tier-1 bottle makers must itself trade in glass, or the path is not commodity-carrying
and the sole-source premise fails. That is not a contrivance: a real glass chain is a chain of glass
companies, raw glass and cullet feeding tubing and preform makers feeding bottle makers, with Cascade
at the raw end. The requirement makes the topology more honest, not less.

**The measure names a commodity generically, never glass.** The governed text says "the commodity at
risk" and the question supplies the commodity. A definition that hardcodes glass reads as though it
were authored backwards from this demo's answer, which is the first thing a sharp room would suspect
of leg 1. It also survives a reseed. On stage the presenter asks about glass, the rule on screen says
"the commodity at risk," and the graph resolves it, which is itself evidence that the definition was
standing rather than written for the question.

Two things follow, and they are the demo:

- **One business unit is sole-sourced.** Every one of its glass bottle suppliers traces back to
  Cascade. Not most. All of them.
- **The other business units are genuinely protected.** Each has at least one glass supplier with no
  Cascade dependency at all.

That contrast is the argument, and it is a true structural fact rather than a tuned one. `MEAS-01` and
`RULE-07` get rewritten to scope by commodity and to report sole-source concentration per business
unit rather than bare reachability. Draft the wording before touching code, since it is the governed
definition the graph reads aloud on stage.

**The rewrite changes the population, not the arithmetic.** `MEAS-01` stays a revenue measure at grain
business unit and fiscal quarter, aggregating `sum(revenue_entries.amount)`. Commodity scoping and
sole-source both live in the predicate that decides which business units are in scope. That is not a
compromise to protect Beat 4's figure, it is the division of labor written into the measure itself:
the graph decides which units are exposed, the lakehouse computes how much. Moving concentration into
the aggregation would blur the one thing Beat 4 exists to show. It would also require a second measure
and break the one-measure-per-term assert, which is the mechanical reason the same answer is forced.

---

## Story 1 staging

*In short: Beat 3 shows definition, then discovery, then explanation as three distinct outputs on
screen, Beat 4 is the handoff made visible, and no beat scripts a Run A answer.*

The five beats, the frozen question text, and the notes on how each beat is narrated are contract
sections 5 and 6. What follows is only what a presenter needs that the contract does not carry.

**Beat 3 shows all three legs producing distinct visible output, in order.**

1. **Definition.** The ontology states what a Critical Supplier is: RULE-05, TERM-05, THR-03. On
   screen as authored text, before any score appears. This is where the contrast with Beat 2 lands.
2. **Discovery.** Betweenness ranks the supplier network and names Cascade Glassworks, which supplies
   no business unit directly and appears in no Americas supplier list. Nobody asked about Cascade.
   Nothing pointed at it. This is the output of the algorithm, on screen.
3. **Explanation.** The multi-tier traversal shows why: every one of the Americas glass suppliers from
   Beat 2 converges on Cascade through the sub-tier. The diversification was illusory, and this is the
   path evidence for it, on screen as paths.

The shape of the beat is the reframe. Run A answered the question it was asked, and answered it
competently. The graph comes back with an answer that has a definition behind it.

**Beat 4's handoff is the division of labor made visible.** The graph supplies the concentration
fact: only the Americas is sole-sourced to Cascade, and the other units have independent glass. Genie
then computes recognized revenue per business unit for the most recent full quarter. Say plainly that
this is the lakehouse's query on the lakehouse's data, the same query Run A could have run. Contract
section 5 carries the causal step and the kicker.

**The convergence question to invite, verbatim.** Contract section 4 says to invite it rather than
hope nobody asks. This is the phrasing: "do all our Americas glass bottle suppliers share a common
upstream supplier?" Run A answers it correctly, at least while Cascade sits one hop away. This sits
alongside the existing "if challenged, invite the shortcut" note in `DEMO.md`.

**No plants in Beat 1.** Today the generator bars every background glass-bottle supplier from the
Americas so the answer is a fixed count. Let the answer be whatever the topology produces. The finding
is "all of them trace to one furnace," which is a stronger business point and requires nothing to be
rigged.

---

## The vocabulary guard

*In short: a mechanical check over every surface Run A can see, run at build time and again on demo
day, plus a human review for the paraphrases a mechanical check cannot catch.*

Contract section 7 asserts that no governed vocabulary is visible to Run A. This is how.

Four surfaces can leak one: Unity Catalog table and column names, table and column comments, the Genie
space text instructions, and the space example SQLs.

**The mechanical guard.** The governed vocabulary already exists as data in the generator: the term
names, the rule names, and the `TERM-`, `RULE-`, `MEAS-`, `THR-` and `GM-` identifiers. Export it as a
list. Then a check pulls every table name, column name, table comment, and column comment in the
schema from `information_schema`, plus the Genie space export, and fails if any of them contains a
governed string. This runs as part of the build, not as a manual review step.

**It must also run standalone, because the build is the wrong and only time it currently fires.** The
Genie space is hand-synced through the `manage_genie` MCP tool, so anyone who touches the space
between the build and the demo can reintroduce a leak with nothing to catch it. Write the check as
something callable on its own, and run it twice: once during the rebuild, once in the pre-flight on
the day. It protects the load-bearing claim, which makes it the check most worth running last rather
than only first.

**The commodity-grouping extension.** The guard also fails if any table comment, column comment, or
space instruction enumerates two or more members of a single commodity's subcategory set. The grouping
is authored knowledge and hands over the traversal filter, but it carries no governed identifier, so
the guard as originally specified would pass it. See the commodity mapping decision above.

**The editorial guard.** The mechanical check catches literal leaks. It cannot catch a paraphrase: a
comment reading "suppliers that bridge many supply paths matter most" passes it and still hands over
the finding. The B5 editorial rule already in `upload.py` stays as the human review for that. The two
are not interchangeable and neither one covers the other.

## The structural asserts

*In short: three asserts prove the network has the shape in which betweenness and degree can
diverge. None of them mention Cascade or a ranking, because asserting the outcome is the banned
move.*

`london-bridge-is-falling.md` diagnosed the failure that killed two earlier passes: on a star forest
every centrality measure collapses into degree, so betweenness becomes a group-by and the graph adds
nothing. Until now that was caught by looking at the output and judging whether it seemed plausible.
It becomes three asserts instead, all of them properties of the topology, none of them mentioning
Cascade or any ranking.

- **The projection is not a forest.** On a forest, edge count equals node count minus component count
  exactly. Assert the edge count exceeds that.
- **At least 30 percent of suppliers are intermediate nodes,** appearing on both sides of
  `supply_relationships`. The original diagnosis was that no supplier was ever both a source and a
  target. The fraction is final and lives in the generator as the named constant
  `MIN_INTERMEDIATE_FRACTION = 0.30`. It is a loose floor on purpose: a real multi-tier chain clears
  it easily, a star forest fails it badly, and a reseed will not spuriously trip it. The assert's job
  is to catch collapse, not to shape data.
- **Traversal depth reaches at least four tiers.** Four is the assert floor and five is the design
  target, and the two numbers are deliberately different. The assert is a tripwire against collapse,
  the target is a goal for the generator, and forcing them to match would either weaken the goal or
  make the tripwire brittle under reseed. The demo does not get more complex with depth: the on-stage
  convergence paths in Beat 3 stay two to three hops regardless, because Cascade sits one tier back
  from the bottle makers no matter how deep the background network goes. Deeper background structure
  strengthens the one-hop ceiling and gives betweenness a real distribution.

None of these assert that betweenness and degree disagree. Asserting disagreement would be fitting the
data to the conclusion, which is banned. These assert that the topology has the structure in which the
two *can* diverge, which is a property of an honest supply network.

**The asymmetry here is deliberate, so it does not get rediscovered as a bug.** The build guarantees
where Cascade is not, meaning top by degree, and does not guarantee where it is, meaning top by
betweenness. The degree constraint protects the topology's shape. The betweenness rank does not need
protecting.

---

## Generator changes (`generate_data.py`)

*In short: rebuild the supply network around one true fact, keep the premise construction distinct
from the banned bar, delete every plant and outcome assert, and accept that the RNG shift moves
every figure.*

Rebuild `make_supply_relationships` around one true fact: one business unit's tier-1 bottle suppliers
all trace back through the sub-tier to Cascade, and the other units' glass suppliers do not. That is
the entire topology.

**The sole-source premise and the banned bar, distinguished before code review collides with them.**
Contract section 8 bans barring background suppliers from a business unit, and contract section 7
asserts that every Americas glass bottle supplier traces to Cascade. Constructing that premise means
the generator decides which glass suppliers the Americas draws from, and that code will look similar
to the bar being deleted below. The distinction is settled here so the rebuild does not relitigate it
midway:

- **The banned bar controlled an answer.** It suppressed background glass-bottle suppliers so that
  Beat 1's count came out fixed, a plant serving a predicted Run A answer.
- **The premise construction controls a relationship.** The Americas unit's glass suppliers are
  assigned from the pool the Cascade chain feeds, and every other unit is assigned at least one
  independent glassworks. Who traces where is the authored premise, stated in the open in contract
  section 7 and asserted at build time. How many suppliers each unit has, and everything Run A says
  about any of them, is left to fall where the topology puts it.

The test for any future edit in this area: if it fixes a count, a score, or a predicted answer, it
is the bar wearing new clothes. If it fixes which structural relationship is true, it is the
premise, and building the premise is the work.

**Keep clustering and enrich it.** Betweenness needs structural holes to be meaningful, so the
background becomes several regional clusters with multiple inter-cluster bridges rather than two
clusters joined by exactly one. Today Cascade is a literal cut vertex, the only bridge in the network,
which makes its betweenness trivially maximal and invites the fair question of why a global supply
network has one bridge. With several bridges, Cascade is the strongest and betweenness returns a real
distribution instead of a single spike.

**The extra bridges must not become fake glass paths.** This is where the two goals pull against each
other: more bridges make betweenness interesting, and more bridges give the exposure measure more
places to leak. Commodity scoping is what keeps them compatible, so build the bridges out of
relationships that carry something other than glass and verify the exposure assert still holds after
every topology change.

**The glass chain is the exception to that, and it has to be built deliberately.** Because a
commodity-carrying path requires every supplier on it to trade in the commodity, the sub-tier vendors
between Cascade and the tier-1 bottle makers must themselves carry a glass subcategory. A single
non-glass vendor inserted in that chain breaks the path and the sole-source premise fails silently.
So the glass chain is constructed as a chain of glass companies and everything else in the background
is built to carry something other than glass.

**The glass chain gets real intermediate subcategories.** Not one raw glass cohort doing double duty
as both Cascade's peers and the sub-tier. Four reasons, and the last one decides it:

- **Double duty breaks the cohort check.** `WHERE subcategory = 'raw glass'` is supposed to return
  Cascade's genuine peers, other furnaces. If raw glass is also the sub-tier, the check is satisfied by
  Cascade's own customers and stops meaning anything.
- Contract section 8 bans reserving a subcategory for one supplier, and double duty is the muddy
  neighbour of that rather than a clean escape from it.
- **The RNG shift is already accepted.** The delete list above states the blast radius is every figure
  in `ground_truth.json` and that this is fine. Two more subcategories is the same class of change, not
  a new one.
- **Real tiers give Cascade more honest betweenness.** Several vendors at each intermediate tier
  multiplies the distinct paths converging on the furnace, and one flat cohort does not. Cascade has to
  clear the 95th percentile on its own merits with two topology iterations before the stopping rule
  fires, so structure spent here is the cheapest insurance available.

**Two depths, deliberately different, and both already required above.** The glass chain stays shallow,
Cascade to sub-tier to tier-1 to business unit, because Beat 3's convergence paths have to be legible
on a screen. The four-tier assert is cleared by the background network, which is also what gives
betweenness a real distribution.

**The risk to carry into the rebuild rather than solve now.** Cascade's betweenness comes from the
whole network and the other inter-cluster bridges are required to be non-glass, so it is possible
Cascade cannot clear the percentile on glass structure alone. That is exactly the case contract section
7's stopping rule describes: check whether the sole-source assert passes first, and escalate rather
than take a third run at the topology.

**Scale.** Enough graph that the answer is not eyeballable on a whiteboard, and roughly five tiers deep
by traversal. The current scale is already in that range. Do not treat the existing row counts as a
target to hit. The build asserts a four-tier floor, deliberately below this target, per the structural
asserts section.

Delete:

- `SUP_HUB_DEGREE_MARGIN` and the decoy-hub boost loop. Leave SUP-109 as an ordinary supplier rather
  than removing the row, so downstream RNG draws do not shift for no benefit.
- `CASCADE_A_LINKS` and `CASCADE_B_LINKS` as hand-tuned counts.
- the `americas_glass == set(TIER1_IDS)` assert and the glass-bottle bar in `make_supplies`.
- the "raw glass is reserved for Cascade" reservation, so the subcategory holds a cohort.
  **This shifts the RNG stream and there is no way around it.** `make_suppliers` runs early in
  `main()`, ahead of the ownership, invoice, revenue, finding, supplies and supply-relationship
  makers, off a single shared `rng`. Two independent shifts follow, not one:
  - Adding `raw glass` to `SUPPLIER_SUFFIX_BY_SUBCATEGORY` adds a name pool, and the name-pool setup
    shuffles once per pool, so it adds an `rng.shuffle`.
  - Adding `raw glass` to `SUBCATEGORIES["packaging"]` changes the `rng.choice` in the supplier loop
    from four options to five.

  **The blast radius is every figure in `ground_truth.json`,** not just Story 2: the delinquent cohort,
  the ownership DAG, both exposure totals, Beat 4's revenue figure, and the whole supplier network.
  That is expected and it is fine, per contract section 9. What must survive is the structural asserts,
  and re-verifying them is part of this step rather than a follow-up.
- the rank-disagreement asserts.
- the `pairs_separated` strict-max assert. It asserts the narrative before the algorithm runs.
- the cut-vertex assert, replaced by the connected-component check.
- **the hardcoded currency band in `check_exposure`.** It asserts BU-03's last-quarter revenue falls
  inside a fixed range, which is exactly the shape contract section 9 bans: the first reseed that moves
  revenue outside the band fires it spuriously, and the obvious "fix" is to widen the band, which
  teaches the next person that asserts are negotiable. The recompute check immediately above it already
  does the honest work, confirming the figure sums the right unit, the right quarter, and the right
  column.

Add:

- **A build-time quarter assert.** `AS_OF` is `date.today()` at generation, so Beat 4's quarter is
  derived from the build date and revenue covers the trailing twelve months from it. Assert that the
  generated data actually covers the quarter it was shaped and asserted around, and record that
  quarter in the build identity alongside the seed and the git sha.

  **This is not the same check as the day-of one, and conflating them is how the gap survives.** A
  build-time assert cannot catch a quarter that rolls after the build. The day-of check is in the
  pre-flight list below and is a comparison against the recorded quarter, not generator code.

Knowledge layer, which is the customer's architecture and stays:

- **TERM-05 and RULE-05 are reopened, and both lose their superlatives.** An earlier draft of this
  plan said TERM-05 stays as written. That line predates the cohort decision and is out of step with
  the contract. TERM-05 says "the narrowest bridge" and RULE-05 says "the highest-betweenness bridge,"
  both strict maximum, while contract section 7 makes THR-03 cohort membership and forbids the
  one-winner shape outright. They cannot both stand. The threshold semantics are settled in the
  contract, so the wording is what moves.

  RULE-05 also fails the readability test this phase is meant to apply: "the highest-betweenness bridge
  at or above the supply concentration threshold" is a restatement of a graph metric, which is the
  named failure mode. The fix is structural rather than cosmetic, business meaning in the first clause
  and measurement in the second. **No assert has to be relaxed for this.** The generator requires
  RULE-05's expression to contain the literal strings `Critical Supplier` and `SUPPLIES`, and both
  survive when the graph vocabulary sits in the measurement clause. The rule is that graph vocabulary
  never appears in the clause that says what the term means.
- **Keep the threshold. It is the strongest single artifact leg 1 has.** "Review any supplier at or
  above the 95th percentile of supply betweenness" is a sentence a risk committee genuinely writes and
  the lakehouse has no equivalent of anywhere. A cohort is also more defensible on stage than a single
  winner, which invites the room to ask whether it was tuned.
- **GM-01 needs no rewrite and no new term or metric is added.** The one-metric-per-term and
  one-measure-per-term asserts stay intact.
- **`MEAS-01` and `RULE-07` get the commodity-scoped rewrite** described above, changing the population
  predicate and not the aggregation.
- **THR-03 becomes a hand-set percentile,** review any supplier at or above the 95th percentile of
  supply betweenness. A raw betweenness constant means nothing to a committee. A percentile is language
  a committee genuinely writes, it is chosen before the run, and it deliberately catches a cohort. Note
  the plumbing: the percentile is the governed parameter and lives in the generator, but the cutoff
  value it resolves to can only be computed once betweenness has run, so `gds.py` still writes the
  resolved value. That is not a post-hoc threshold, because the rule was fixed before the algorithm
  ran. Contract section 7 carries the immovability guard and the stopping rule.

  **The percentile is visible in the graph, in its own field.** `thresholds.csv` gains a text column
  `basis`, holding the percentile as authored language for THR-03, while `value` keeps holding the
  cutoff `gds.py` resolves. `load.py`'s threshold `NodeSpec` needs no type entry for it, since `value`
  remains the only numeric field. The other thresholds leave `basis` empty, which `currency` already
  does on the two integer thresholds.

  The reason is Beat 3 rather than tidiness. RULE-05's expression ends "at or above the Supply
  Concentration Threshold," so the room's next question is what that threshold is, and leg 1 is the
  load-bearing leg. Answering with a bare betweenness score, which has no units and no meaning to a
  committee, is the weakest possible moment for the strongest artifact leg 1 has. It also makes the
  input and output split structural: the percentile is pinned across reseeds, the cutoff moves on every
  build, and one column cannot honestly hold both.

  **THR-04's `basis` stays empty on purpose.** Its honest text would describe a cutoff placed between
  the protagonist and the runner-up, which is a fitted value rather than a governed parameter. That is
  the one-winner shape THR-03 just lost, and contract section 8 bans redesigning Story 2, so the field
  is left empty rather than backfilled. A side effect worth keeping: the column documents which
  thresholds are governed and which are not.

No minimum-cohort clause and no 80 percent rule.

## GDS changes (`gds.py`)

*In short: keep betweenness and the projection check, resolve THR-03 from the governed percentile,
assert cohort membership rather than a winner, and add the Story 2 checks that exist only in prose
today.*

- **Keep `compute_betweenness`.** Add `concurrency: 1` for symmetry with PageRank. Note that the reason
  it is currently unpinned is sound: `samplingSize` is already pinned to `nodeCount`, which makes it
  exact Brandes, and the existing comment block explains why that is already deterministic. PageRank
  pins concurrency because it is tolerance-based, which betweenness is not. Adding it costs nothing at
  this node count. Do not generalize the reasoning.
- **Keep `check_supplier_projection`** and its UNDIRECTED comment block. It is cheap and it guards the
  thing that matters, that the projection is the raw-material chain and not the customer-facing
  fan-out.
- **Rework the THR-03 computation** to resolve the generator's percentile rather than compute a
  one-winner cutoff. `place_cutoff` and `concentration_cutoff` for Story 1 go, and the percentile
  resolution replaces them.
- **Delete the strict-max requirement in `assert_betweenness`.** Replace it with the cohort check:
  Cascade clears THR-03. Report the ranking, do not assert who wins.
- **Add the three-legs resolution check** as a real query against the loaded graph: RULE-05's text is
  retrievable, Cascade's node carries a betweenness property, and the convergence traversal returns at
  least one path. Nothing verifies this today. `gds.py` asserts the scores it computes, but nothing
  walks TERM-05 to RULE-05 to THR-03 to confirm the path resolves, and that walk is Beat 3's leg 1,
  which is the load-bearing leg of the load-bearing claim.
- No canonical relabeling. If a data change moves the output, re-capture the demo script.
- Leave the Story 2 path untouched, including `place_cutoff` itself, which `contagion_cutoff` still
  uses for THR-04.
- No Louvain. No new projection.

**Add the three Story 2 landmine asserts.** These are load-bearing behaviors recorded in prose in
`london-bridge-is-falling.md` and checked nowhere. The regenerate re-rolls the data they depend on, so
they become asserts alongside the existing Jade check rather than tribal knowledge in an archived
document.

- **The holdco filter excludes holdcos and actually removed someone.** If it removes zero rows it has
  silently stopped working, which looks identical to it working.
- **Every filler default is part of a parent and subsidiary pair** holding each other in the intended
  stake band. A default with a single neighbour dumps all its PageRank mass onto that neighbour
  regardless of weight, which is why the pairing exists. Today nothing checks it.
- **PageRank converged.** Assert `ranIterations` is below `maxIterations`. Hitting the cap means it did
  not converge and the ranking is unreliable, which is the failure that forced the bump to 200 in the
  first place.

## Docs

*In short: every document, diagram, and the Genie space gets reconciled to the rebuilt data, and
each claim of done is verified against the live workspace rather than the worklog.*

- `DEMO.md`: rewrite the Story 1 beats around the grounding spine. Beat 2 becomes a live repeated ask
  with no scripted Run A answer. Beat 3 stays a single beat and shows the three legs in the new order,
  definition first, and carries the criticality side-by-side. Rewrite Beat 4 around the five-unit
  comparison, add the bottles causal argument, delete the honesty caveat about the number not being
  attributable to Cascade, which was true of the unscoped measure and is not true of this one. Replace
  the rationale section with the three legs and the two-claim rule. Carry the honest caveat about
  convergence being cheap in SQL, and add the note about inviting the convergence question. Remove
  quoted counts and scores. **Delete any "expected Run A answer" material and do not reintroduce it in
  another form.** The "Genie space and MCP setup" section describes standing infrastructure and is not
  rewritten by this work. **`DEMO.md` quotes the old TERM-05 phrasing "the narrowest bridge" in two
  places, including once as the finding Beat 3 lands on.** Both go when the superlative does, so this
  is a required edit rather than a stylistic one.
- **The Story 1 diagram.** It currently shows Cascade feeding one unit and nothing else, which
  contradicts what the graph answers live. After commodity scoping the diagram becomes true again, but
  redraw it to also show the independent glassworks feeding the protected units, because that contrast
  is now the argument in Beat 4. It must also show Cascade one tier back from the bottle makers, which
  is the hidden choke point shape.
- `README.md` and `DATA_ARCHITECTURE.md`: Story 1 threshold semantics and the new exposure wording.
  Both describe the two-cluster-bridge topology in prose in several places and go stale under the
  rebuild.
- `upload.py` and the Genie space. Root causes 1 and 2 of the v2 failure were the space and the Unity
  Catalog semantics falling out of step with a rebuilt schema, which is exactly what this rebuild does
  again, so treat this as a build step rather than a doc chore. Items:
  - The subcategory column comment. **The raw glass example list is already removed.** Re-read after
    the rebuild to confirm it stays neutral. No rewrite work is outstanding.
  - The `supply_relationships` entry in the SEMANTICS dict. **Already rewritten to the neutral version
    and verified in the probe.** Re-read after the rebuild to confirm it stays accurate. No rewrite
    work is outstanding.
  - The Genie space `column_configs` and example SQLs. **These are not in this repo.** They live on the
    Databricks Genie space and are hand-synced via the `manage_genie` MCP tool, so grepping the
    codebase for them finds nothing but worklog references. **The probe verified that no example SQL
    touches `supply_relationships`.** Re-sync the region and subcategory filters after the schema
    changes and re-verify that the examples still do not prime Genie toward Cascade.
  - The space text instructions use the word "diversification" when telling Genie to filter to a named
    scope before ranking or judging. That is not a Cascade prime and not a traversal prime. Leave it.
    It may contribute to the axis Genie picks in Beat 1, and under the current framing that is
    demonstration material rather than a leak.
- `load.py` references the betweenness path and stays accurate.
- `expected_results.py` carries no betweenness, THR-03, TERM-05, RULE-05, or GM-01 rows and does not
  need any. Leave the shape alone.
- **The transcript PDFs.** Move the existing v1 and v2 sets to `worklog/archive/transcripts/`. After
  the rebuild every transcript from both stories is stale by definition, because the regenerate moves
  every figure. Capture a v3 set for both stories in the re-probe phase and do not compare it against
  v2. Stamp each new transcript with its build identity, meaning seed, as-of date, and git sha, so
  which build a transcript came from is never a question again.

  Transcripts are dated evidence of a past run, never a target. This plan builds new demo data and a
  new flow. No prior result is something the new build has to reproduce.

---

## The phases

The script is written from transcripts rather than from expectations. That principle survives the
reframe and gets stronger: transcripts are now read for whether an answer cites a definition, never
for whether it matches a prediction.

Phases are referred to by name rather than by number wherever another document points at one, because
renumbering has broken cross-references here before.

### Phase 0, the Run A probe

**Complete, 2026-07-19.** Both halves are captured in `probe-run-a.md` and summarized in "What the
probe established" above. Nothing in this phase touched the repo.

This was never an attempt to pin down what Run A will say. It cannot be pinned down and we stopped
trying. It is a measurement of variance plus a confirmation of the claim the demo rests on, and
neither result can be invalidated by the topology rebuild.

### Phase 1, the governed wording

**Complete, 2026-07-19.** All four texts are operator-approved and landed in `generate_data.py`. The
check that proves it, per contract section 10: `check_ontology()` passes against the new wording, and
no assert needed relaxing, because RULE-05's expression still carries the literal `Critical Supplier`
and `SUPPLIES` strings the generator requires. The approved wording is recorded below under "The draft
wording", which is now the landed wording rather than a proposal.

One editorial item is outstanding: `TERM-05` says paths carry a commodity "into the business" while
`RULE-05` says "into a business unit". Per-unit is the correct scope and matches `MEAS-01`, so
`TERM-05` is the one to align. It lands before the rebuild starts, not after: this plan's own gate
logic says the wording is an input to the topology, and a one-word alignment is not worth an
exception to that.

Draft the governed text for `TERM-05`, `RULE-05`, `MEAS-01` and `RULE-07`, get it approved, and land
it. Nothing else.

**The offline verification step is dropped and folded into the rebuild.** An earlier draft asked for a
query against today's data showing the scoped measure behaves as the wording says. On today's topology
that check can only show that commodity scoping narrows the answer, which is already known, and it
cannot show the sole-source premise, which is not true until the rebuild creates it. The real check is
contract section 7's exposure assert, and it belongs where it can actually run.

**What survives is the drafting, and it stays a gate rather than folding into the rebuild too.** The
wording is an input to the topology, not an output of it. The commodity predicate decided above is
what tells the rebuild that the sub-tier vendors must trade in glass. Build the topology first and it
gets built against text nobody has read.

**Read `RULE-05` and `TERM-05` out loud in the same pass.** With ontology promoted to the first of the
three legs, these two are carrying the contrast. Beat 3 opens by asking what "Critical Supplier"
means, and `RULE-05` is the answer the lakehouse cannot give. That makes its exact wording
load-bearing in a way it was not when the algorithm led. Read both the way a risk committee would hear
them and check three things:

- Does it read as an authored business definition, or as a restatement of a graph metric? "A supplier
  whose betweenness exceeds THR-03" fails this test. The rule must be stated in business terms, with
  the metric as how it is measured rather than what it means.
- Would a procurement lead recognise it as a rule their organisation could have written?
- Does it stand on its own on screen, without the presenter explaining what it means?

Do not assume these are settled because they predate the reframe. They were written when the algorithm
was the first leg and nobody has reread them since.

**Every draft in this phase goes to the operator for review before it lands.** The wording is script
material read aloud on stage, so sign-off precedes any edit to code or data.

#### The governed wording, approved and landed

**Where the absolutism lives, which is the decision behind all four texts.** A first draft had
`TERM-05` and `RULE-05` saying the supply base cannot route around a Critical Supplier, meaning losing
it stops supply outright. That contradicts the measurement. THR-03 is a percentile and contract
section 7 requires the clearing cohort to have more than one member, so most Critical Suppliers are by
construction ones the business *can* route around, and a sharp room asks about it. The threshold's own
name was already the tell: it is the Supply **Concentration** Threshold.

So the definition and the rule speak in concentration language and the sole-source absolutism lives in
`MEAS-01` and `RULE-07`, where contract section 7 asserts it is actually true. This is also the better
beat order. Leg 1 puts a cohort on a watchlist, which is the kind of rule a committee writes, and Beat
4 then shows that for one business unit and one commodity the dependency happens to be total. Opening
at absolute discards that escalation.

**TERM-05, Critical Supplier.**

> A supplier that a disproportionate share of the multi-tier supply paths carrying a commodity into
> the business run through, leaving few alternatives around it. A Critical Supplier need not sell to a
> business unit directly, and often does not.

No superlative, no metric, and the last sentence is what makes the hidden choke point legible to a room
without the presenter explaining it.

**RULE-05, Critical Supplier Rule.** Expression:

> A supplier is a Critical Supplier when a disproportionate share of the supply paths carrying a
> commodity into a business unit run through it, leaving the unit few alternatives if that supplier
> stops. Measured as supply betweenness over the multi-tier SUPPLIES network, at or above the Supply
> Concentration Threshold.

Business meaning in the first sentence, measurement in the second. Contains the literal `Critical
Supplier` and `SUPPLIES` the generator asserts on, so no assert changes.

**MEAS-01, Supply Exposure.** Grain and aggregation unchanged, at business unit and fiscal quarter over
`sum(revenue_entries.amount)`. Definition:

> The recognized revenue that stops when a Critical Supplier stops: the most recent full quarter of
> recognized revenue for every business unit whose supply of the commodity at risk depends wholly on
> paths through that supplier. A path that does not carry the commodity creates no dependency and is
> excluded.

**RULE-07, Supply Exposure Rule.** Expression:

> sum(revenue_entries.amount) over the most recent full calendar quarter, for every business unit whose
> entire supply of the commodity at risk runs through the supplier, counting only paths on which every
> supplier trades in that commodity.

Description:

> The recognized revenue at risk behind a Critical Supplier. A business unit is exposed when every
> commodity-carrying supply path for the material at risk passes through that supplier, so reachability
> through suppliers trading in something else does not count. The graph decides which units are in
> scope and the lakehouse computes the amount.

**Exit criterion, met.** All four are operator-approved and landed in `generate_data.py`, and
`check_ontology()` passes with `RULE-05`'s expression still carrying the literal `Critical Supplier`
and `SUPPLIES` strings the term-salience asserts key on. `TERM-05` and `RULE-05` both changed, for the
superlative reason and the concentration reason above. `MEAS-01` and `RULE-07` changed to the
commodity-scoped population predicate with grain and aggregation untouched.

### Phase 2, the guards

*In short: every guard is written and proven green against the current build first, so when the
rebuild breaks something the failure is unambiguously in the data. The Run B routing probe joins
this phase because its worst outcome must not be discovered last.*

**In progress.** The THR-03 percentile constant is committed on its own, ahead of any topology work,
per the immovability guard in contract section 7. That is what makes "chosen before the run" a fact
anyone can verify from git history rather than a claim in a document. A pre-rebuild baseline of the
green build is captured in `../worklog/pre-rebuild-baseline.md`.

**Why this is a separate phase from the rebuild, given the plan previously refused to split.** The
earlier draft split the work into generator changes, GDS changes, and reload, and that split was
fiction: the topology rebuild, the betweenness rework, and the reload are one regenerate cycle that
gets run repeatedly until it comes out clean. Splitting the cycle is still fiction and is still
refused.

This is a different cut, along a line that is real. Everything in this phase can be written and
verified against the **current green build**, with the topology untouched and the RNG stream unmoved.
Everything in the rebuild phase cannot. Landing the guards first means that when the rebuild breaks
something, the guard is already known good, so the failure is unambiguously in the data rather than in
the check. The baseline capture already demonstrated the value of that ordering by falsifying two
diagnostics that had been written into this plan from reasoning alone.

Nothing in this phase changes the topology, and nothing in it reseeds. The one regenerate it needs, for
the `basis` column, adds a field without touching any RNG draw, so the ownership and supplier data come
back identical and the baseline stays valid.

Contents:

- The three Story 2 landmine asserts, written and confirmed passing against known-good data.
- The three-legs resolution check against the currently loaded graph.
- The vocabulary guard, built as something callable standalone, then run against live Unity Catalog and
  the live Genie space. If it fails today, that is a finding worth having before the rebuild rather
  than after.
- The build-time quarter assert, and recording the build identity alongside the seed and the git sha.
- The `basis` column on `thresholds.csv` and the matching `load.py` `NodeSpec` change.
- **The Run B routing probe, against the current green build, recorded in `probe-run-b.md`.**
  Contract section 5 makes a routing defect, meaning Run B never reaches the graph at all, the one
  Run B result that stops the demo, and until now it was scheduled to be discovered last, after the
  full cost of the rebuild was already paid. Routing is a property of the MCP wiring and Genie One's
  tool selection, not of the data, so the answer survives the rebuild the same way the Phase 0
  reflex findings do. This probe answers one question only: does Run B reach the graph. What Run B
  says on the rebuilt data, and whether it cites the definition unprompted, stays in the re-probe
  phase.

**Exit criterion:** every item above passes against the current build, with `data/` otherwise
unchanged. A guard that has never been seen to pass is not a guard. For the routing probe, passing
means a recorded transcript in which Run B reaches the graph.

### Phase 2.5, the rebuild

*In short: one regenerate loop, run repeatedly until every assert is green. The hard judgment is
telling a broken premise from a moved output when a Story 2 assert fails, and the decision rule
below settles it in advance.*

The generator changes, the GDS changes, `make demo`, and `make expected`, in one batch, run repeatedly
until it comes out clean. Numbered 2.5 rather than 3 on purpose: this plan refers to phases by name
because renumbering has broken cross-references here before, and inserting a phase would renumber the
re-probe and the docs.

**Precondition: a clean tree.** The guards and the wording land as commits before the first
regenerate runs. `../worklog/lessons-learned.md` records a regenerate on a dirty tree destroying
uncommitted data, and this phase is one long regenerate loop, so the rule is applied here rather
than remembered.

**Exit criterion:**

- The generator runs clean and every contract section 7 assert passes, including the degree
  constraint, the exposure constraint, the vocabulary guard, and the three structural asserts.
- THR-03 resolves from the generator's percentile, Cascade clears it, and the cohort clearing it has
  more than one member.
- The three-legs resolution check still passes against the rebuilt graph.
- Two consecutive runs produce the same betweenness ranking.
- Story 2 still holds: the Jade assertion passes, THR-04 still sits between Jade and the next trading
  customer, and the three landmine asserts pass.

**When a Story 2 assert fails, ask whether a premise broke or an output moved.** The regenerate
re-rolls the filler groups that Jade is ranked against, so this is a live possibility rather than a
hypothetical, and the two cases have opposite correct responses. Reseeding until it passes is not one
of them: contract section 9 makes the asserts the thing that fails loudly when a reseed breaks a
premise, and seed-shopping is what that rule exists to forbid.

The four asserts are not the same kind of check.

- **The three landmine asserts are construction facts.** The holdco filter excluded holdcos and
  removed someone, every filler default sits in a parent and subsidiary pair, and PageRank converged.
  A failure means the generator built something wrong. Fix the generator, no judgment call.
- **`assert_pagerank` is not.** It asserts Jade is the top trading customer by weighted PageRank, and
  `contagion_cutoff` places THR-04 between Jade and the runner-up so that only Jade clears it. That is
  the one-winner shape contract section 8 bans and that THR-03 just lost, surviving in Story 2 only
  because Story 2 was out of scope. So "fix the generator" here can mean adjusting filler stakes until
  Jade wins again, which is tuning data so an algorithm output lands a specific way.

**The premise is about what reaches a clean account, not about stake size.** An earlier version of
this block keyed the test to `FILLER_STAKE_RANGE` and to the presence of a controlling chain. The
pre-rebuild baseline falsified both against a build where every assert passed, so they are recorded
here as wrong rather than quietly replaced.

`FILLER_STAKE_RANGE` is not an invariant of the emitted data. It seeds the skeleton draw in
`make_ownership`, and three later steps in that same function put stakes outside it: the joint-stake
block draws from a wider band, and the post-default rewrite pushes edges between two defaulted parties
high and edges with one defaulted endpoint low. A meaningful share of filler edges sit outside the
band on a green build. A controlling multi-level chain is not a violation either, because the counting
decoy already carries one, structurally the same shape as Kestrel over Harbour. It takes nothing from
Jade because every node on it is defaulted, so it terminates in defaults and delivers to no clean
account.

What was actually true on the green build, stated as a relationship rather than a value, per contract
section 9:

- Fat stakes run only between two defaulted parties.
- A clean owner's stake over a defaulted subsidiary stays small.
- No controlling chain terminates at a clean trading account. Jade's does, and that is what makes
  Jade's accumulation structural rather than incidental.

So the test is whether a clean trading account other than Jade came to sit under concentrated
ownership of failure. If a reseed gave some clean account a controlling chain terminating on it, or
stacked joint holdings so it absorbs from several defaulted co-owners at once, the filler generator
broke its own premise and fixing it is the work. If no clean account gained either shape and Jade
still lost, then weighted PageRank is not measuring what Story 2 claims on this network. That is a
finding, not a tuning problem, and it escalates the way contract section 7's stopping rule escalates.
Two honest iterations, then stop.

**Suspect the joint-stake block first.** Jade's runner-up on the green build holds no controlling
stake anywhere. Its score comes entirely from joint holding alongside a defaulted co-owner, which
makes `JOINT_STAKE_RATIO` and the joint-stake band the likelier route for a filler to overtake Jade
after a reseed than any controlling chain.

**If the fix requires moving THR-04 to a cohort percentile, stop and escalate.** That is the THR-03
fix applied to Story 2, and contract section 8 bans redesigning Story 2, so it needs that line
reopened rather than worked around.

**Verify against the live workspace, not against the worklog.** Twice in this project's history a
change recorded as applied and verified was absent from the deployed system, and one of those root
causes was never found. So the Unity Catalog semantics are read back from `information_schema` after
upload and compared against the SEMANTICS dict, not "the statement was issued" but "the comment was
read back." And the Genie space is fetched and checked: expected tables present, banned tables absent,
vocabulary guard clean.

### Phase 3, the re-probe

*In short: re-ask every question on the rebuilt data, watch whether Genie recurses now that Cascade
sits two tiers back, and write the beats from the transcripts, never before them.*

Re-run all four probe questions against the rebuilt data, plus the Beat 1 spread run. Read the
betweenness output. Then write the Story 1 beats from what came back.

**The single most important question in this phase: does Genie ever reach for recursion once Cascade
sits two tiers back?** The one-hop ceiling is what the demo's structure relies on. The prediction to
test is that a one-hop query returns the sub-tier vendors and stops, Cascade never enters the result
set, and Genie's summarizer therefore has nothing to notice. If Genie writes a recursive CTE at that
point, the structure of the beats needs rethinking. Note that the load-bearing claim survives even
then: a recursive answer still cites no governed definition.

Also re-probe the exact phrase "common upstream supplier." If Genie responds by adding a second hop by
hand rather than by recursing, the convergence caveat needs stating more carefully than "one join."

**Probe Run B on the rebuilt data, continuing `probe-run-b.md`.** The routing question, whether Run
B reaches the graph at all, is answered in the guards phase, because it is the one Run B result that
stops the demo and it must not be discovered last. What remains here is behavior on the rebuilt
data. The plumbing is standing already, per contract section 8, so this is asking questions rather
than building anything. Ask the Beat 1 and Beat 3 questions through Genie One and record what comes
back. The question worth answering is whether Run B cites the definition unprompted or has to be
steered into it, which per contract section 5 is a staging note rather than a failure.

**The beats are written from the output, never before it.** There is no adjust-the-script escape hatch
and there are no exceptions to it. If a run answers something other than what a beat expects, the beat
is rewritten to match the transcript. The data is rebuilt only when a structural assert fails, never
because of something Genie said.

**Run A naming Cascade unprompted is not a failure.** An earlier draft carved this out as the one case
where the topology gets fixed instead of the beat. That exception is deleted. It was the old
predict-and-defeat reflex surviving in a single line, and it does not survive contact with the
grounding claim: Genie can name Cascade and still cite no governed definition, so claim A is untouched
and the demo is intact. What it costs is one line of staging. Beat 3's discovery leg wants to say the
graph found a supplier nobody was looking at, and that falls flat if Run A named it five minutes
earlier. The response is to re-stage, not to re-cut the data: lead Beat 3 with the definition leg,
which is leg 1 and entirely unaffected, and let discovery land as confirmation rather than as reveal.

The hidden choke point requirement stays, for an honest and weaker reason than before: a choke point
that is trivially visible makes the graph look unnecessary. That is a demo-quality argument, not a
claim-integrity one.

**Exit criterion:**

- Transcripts for all four questions from the rebuilt data, plus a Beat 1 spread run.
- The Run B behavior probe recorded in `probe-run-b.md`, continuing the routing probe captured in
  the guards phase.
- A betweenness top-N read and recorded.
- Five beats written that match what the transcripts say and that contain no scripted Run A answer.
- **The three legs produce three distinct visible outputs on screen in Beat 3.** The guards phase
  asserts they resolve and the rebuild phase re-confirms it. No build can check that they read as three different things to a room, so this
  is the editorial half and it belongs here. If two of them land as the same slide, the beat needs
  restaging.

### Phase 4, the docs

Docs and the diagram, per the section above.

**Exit criterion:** `DEMO.md`, the diagram, `README.md`, `DATA_ARCHITECTURE.md`, and the Genie space
are all consistent with the re-probe transcripts, and no reseed-variant value remains in prose or in a
diagram label. The Genie space check is a fetch from the live workspace, not a reading of this
worklog. The v1 and v2 transcripts are archived and the v3 set is captured and stamped with its build
identity.

## Checks that belong to no single phase

*In short: the claims that must hold at any moment, plus the two pre-flight checks that only mean
anything on the day.*

Every other check in this plan is a phase exit criterion and is not repeated here. These are not.

**Anytime:**

- **Across every re-probe Run A transcript, no answer cites a governed business definition.** This is
  the load-bearing claim and it is the one that has to pass.
- **A connection count over `supply_relationships` does not name Cascade,** and
  `WHERE subcategory = 'raw glass'` returns a cohort rather than Cascade alone. Ask both directly.
- **Walking Story 1 end to end, Cascade is named in the finding, in the exposure question, and in how
  the figure is presented.**

**Pre-flight, on the day, after everything else has passed.** Both of these guard against drift
between the build and the room, so a build-time pass says nothing about them:

- **The vocabulary guard, run standalone against the live Genie space.** The space is hand-synced and
  can change after the build. This protects the load-bearing claim, so it runs last.
- **Today's quarter still matches the quarter recorded in the build identity.** If it has rolled,
  regenerate before the demo, which is one `make demo`.

## Working-detail additions to the banned list

Contract section 8 is the banned list. These are working-detail items that do not rise to contract
level:

- **Scope creep back into what was already cut.** No `reveal.py`, no clock advance, no banks or
  directors tables, no third story, no new node labels.
- **A number-for-number scorecard between the runs.** The gap is what each engine can ground an answer
  in, not who got closer to a figure.
- **Exhaustive coverage of the graph's capabilities.** One clean instance of grounded versus
  ungrounded.
- **Running GDS live on stage** is banned by the contract, but have the answer ready for the fairness
  objection that not running it invites. Show the run once, briefly, so nobody thinks Run A was denied
  the score. When asked "so the graph just looked up a number you calculated in advance": yes, the same
  way a BI tool looks up a nightly aggregate, and Run A could have had the score too and still would
  not know what it meant.

---

## Rationale archive

Kept so that deleted things stay deleted. Nothing here is part of the plan.

**Why we stopped predicting Genie's answer.** Earlier drafts of this plan tried to predict what Genie
Agent would answer at Beat 1 and Beat 2, then engineer the data so that the predicted answer was
wrong. Every round of relitigation this demo has been through traces back to that move.

It is unwinnable. Genie Agent is backed by a frontier LLM. It is generative and stochastic. The axis
it picks, the tables it joins, and the adjective it lands on are not reproducible, and they change
with model updates we do not control. The probe demonstrated this concretely: the plan and `DEMO.md`
both predicted "well diversified with clean risk scores," and Genie answered "not diversified" on a
different axis entirely and never queried risk score at all. That prediction was made in good faith by
people who knew the schema, and it was still wrong in two independent ways.

Predicting the answer also creates a standing invitation to relitigate. Every time someone reads the
plan and imagines a different plausible Genie answer, the whole argument reopens, because the argument
was built on a specific answer being wrong.

The fix is to move the demo onto a claim that cannot fail: no lakehouse answer cites a governed
business definition, because none exists in the lakehouse. That is true by construction, on every run,
regardless of what Genie says. Run A's variance becomes a live and vivid illustration rather than a
load-bearing assumption. If any future reader is tempted to re-add an expected-answer table, this
paragraph is why not.

**What `archive/locked-plan.md` got wrong.** It carried a requirement that no SQL query may find
Cascade at all. That single requirement generated the decoy hub, the Americas glass-bottle bar, the
rank-disagreement asserts, the one-winner thresholds, and an arms race between the graph ranking and
every SQL aggregate somebody could imagine. Dropping it removed most of that plan and most of the
existing code. The surviving requirement is much narrower: a connection count must not name Cascade,
which is simply what "hidden choke point" means. It also barely used the ontology, which is the
customer's actual EDM point and is now leg 1.

**What `archive/fix-the-arc.md` fixed.** The governed Supply Exposure measure was unfiltered transitive
closure, so Cascade reached every business unit through suppliers carrying no glass and the measure
returned the whole company. Beat 4 papered over this by quietly asking a regional question that never
named Cascade. That was a data-model bug, and commodity scoping is the fix.

**Why the decoy hub is gone.** It pumped SUP-109's degree so that Cascade's degree would not top the
list. That met the constraint by inflating a bystander and hiding it. The current plan meets the same
constraint structurally, by putting Cascade one tier back, and states it in the open. The mechanism is
deleted, the underlying need survives in honest form. SUP-109 stays as an ordinary supplier so
downstream RNG draws do not shift for no benefit.

**Why Louvain was dropped.** An earlier draft argued the question had two halves, diversification and
criticality, so it needed Louvain for the first and betweenness for the second. Three reasons that was
wrong, kept here so nobody adds it back:

1. **Its finding is an easy SQL query.** "These tier-1s share sub-tier vendors" is a self-join with a
   group-by. An analyst reaches for a shared-vendor join far more readily than for Brandes, so the
   community half was the weakest version of the argument, not the sharpest.
2. **It would mostly rediscover the planted clusters.** On a graph this size the strongest modularity
   signal is whatever regional cluster structure the generator builds. Louvain reports those back, and
   the glass cohort ends up as a subset of a larger regional community rather than a legible finding.
   That is the algorithm recovering our own setup.
3. **It cost the room a concept.** Community structure has to be taught before "several of your
   suppliers are one thing" reads as bad news. Betweenness lands as a ranking a risk committee can act
   on without a lesson first.

Diversification is not a separate finding here, it is the setup: the supply base looks diversified,
the ranking says it is not, and the sole-source fact underneath is what makes that true. One algorithm,
one finding, no concept to teach.

**The degree-counting objection, answered.** Betweenness collapses into degree on trees and stars. On a
network with genuine structural holes the two diverge, and the canonical case is the one this demo
wants: a low-degree supplier bridging dense clusters has high betweenness and is invisible to a
connection count. That is what a real supply chain looks like, so the honest fix is a topology with
real structural holes rather than a decoy hub that pumps someone else's degree.

**Why the story moved out of the generator.** Build a topology that is simply true, run betweenness
once, capture what it says, write the script from that. No narrative asserted into existence before the
algorithm runs. This is why the re-probe phase exists and why it comes after the rebuild.

**Why the docs stop quoting numbers.** No scores, no counts, no "roughly twenty" in prose. The script
says "these suppliers all trace to one furnace" and the screen supplies the figures. Genie calculates.
We do not pre-compute the demo's arithmetic into the documentation.

**Why the Beat 1 question lost its second half.** `london-bridge-is-falling.md` flagged "and what is
our single biggest point of failure?" as fragile, because it prompts the convergence query directly.
The probe located the worry precisely: the danger words are "depend on" and "common upstream," and the
criticality phrasing on its own is safe. The clause stays removed because it pulls toward dependency
phrasings, and the criticality question is asked at Beat 3 instead, where the graph answers it with a
definition behind it.

**Why the Beat 3 side-by-side stopped being optional.** An earlier draft banned optional side-by-side
branches, on the grounds that they regenerate the debate the Beat 3 reframe settles. That ban existed
because the beat's payoff depended on Run A giving a specific unsatisfying answer, which made it a
gamble. Under the grounding claim the payoff does not depend on Run A's answer at all, so the branch is
no longer optional and no longer a gamble. It is scripted.

**Why Phase 3.5 existed and why it is gone.** A draft added a phase for Run B plumbing, on the finding
that no MCP server config lived in the repo. The operator had already stood one up with schema
discovery and read-only Cypher, documented in `DEMO.md`, so the phase had no build work in it. What
remained was one assert, which moved into the GDS changes, and one probe, which the re-probe phase
already owned. Recorded so the gap is not rediscovered and re-phased.

**Why the plan stopped re-telling the contract.** An earlier draft carried its own versions of the
claim, the two-claim rule, the three legs, the two runs, reseed invariance, the build guarantees, and
the banned list. Roughly a quarter of the document was a second copy of rules that the contract already
owned, and the contract's own header says it wins on conflict. Two copies of a rule that must be edited
in lockstep is the same drift failure that put the Genie space out of step with the schema twice. The
duplicated sections became pointers.
