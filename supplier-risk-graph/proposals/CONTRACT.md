# Story 1 demo contract

This is the locked short form. It is the authority. `simplified-plan.md` is the working detail
behind it, and where the two disagree, this file wins.

**Rule for changing this file:** anything here is settled. Reopening an item requires saying which
line is wrong and why, not restating a preference. If a proposal does not change a line below, it
is a detail and belongs in `simplified-plan.md`.

---

## 1. The claim

The demo is **ungrounded versus grounded**. It is not wrong versus right.

> Genie alone is a frontier LLM over tables. Ask it a business question and it returns a plausible
> answer grounded in nothing but column names. The axis it picks is generative and not
> reproducible. Genie + Graph returns an answer grounded in an authored
> definition, so it is the same answer every time and a risk committee can act on it.

Supporting statements, both still true and both still used on stage:

> The graph finds the attribution. The lakehouse computes the number.

> Genie alone can compute any number you ask for, perfectly, and still not know which number to ask for.

**What this claim is not.** It is not "SQL cannot express traversal or centrality." SQL can express
both. Its answers are plausible, defensible, and anchored to nothing.

**Genie alone can return an answer that is false at full depth, and that is a legitimate finding.** This
supersedes the earlier absolute that Genie alone is never wrong. The re-probe after the topology rebuild
found one: asked whether the Americas glass bottle suppliers share a common upstream supplier, Genie alone
returns no, because it looks one hop up and the answer sits two hops up. The graph, traversing the
commodity-scoped chain, returns yes and names the supplier. Two runs, one question, opposite words.

The earlier absolute was written to stop a specific failure and it overshot. What it was protecting
against is still banned and is stated in the next paragraph. What it should never have prevented is
reporting honestly what a probe actually found. A demo that has to soften a real result to stay
inside its own framing is a demo arguing with its evidence.

**The line, and it is the whole of it: an emerged wrong answer is a finding, an engineered one is a
plant.** The convergence result qualifies because nobody built it. The topology that produced it was
built to stop Cascade being a cut vertex, the result was discovered by asking, and it would have
been recorded either way. What remains permanently banned is the reverse order: predicting what
Genie will answer, then shaping data so the prediction fails. See section 2's corollary and section
8. If you find yourself reaching for a topology change because a probe answered inconveniently, you
are on the banned side of this line no matter how the result is described afterwards.

**On stage, narrate the mechanism and never the verdict.** The truthful and sufficient sentence is
that Genie looks one level deep by default. It is not incapable of going deeper and could likely be
prompted to, and saying so costs the demo nothing because default behaviour is what a procurement
analyst will actually get. "Genie is wrong," "Genie is bad," and any framing that invites the room
to score one product against another are out. The room should leave thinking about depth of
question, not about which vendor lost. A result that has to be sold as a gotcha will make the room
defend the tool it already owns instead of evaluating the argument.

**Reliability is a separate question and stays Claim B even when a probe run is clean.** A wrong
answer is Claim B whether it is observed once or many times, vivid and not guaranteed, and section 2
governs it unchanged. The convergence result has now been asked five times in five fresh
conversations and stayed at one hop every time, so it is Claim B that has been probed rather than
Claim B that is untested, but it is Claim B still. A clean run is not a guarantee about the next run.
No beat may depend on it, and the beat that carries it must still work if Genie answers the other
way.

**What keeps the claim true.** It holds by construction only while no authored artifact is visible
to Genie alone. The governed vocabulary, meaning the term names, the rule names, and the `TERM-`,
`RULE-`, `MEAS-`, `THR-` and `GM-` identifiers, must never appear in a Unity Catalog table or
column name, a table or column comment, a Genie space instruction, or an example SQL. Section 7
asserts this, and `guard.py` is the check that proves it: it runs inside `make demo`, and standalone
via `make guard`, which is the one to run in pre-flight because the Genie space is hand-synced and
can drift after a build. Genie inventing a plausible-sounding definition is not a failure of the
claim: an invented definition cites nothing, which is the demonstration.

---

## 2. The two-claim rule

This is the most important operating rule in the demo. Two claims, different strength. Keeping them
separate is what stops this from being relitigated.

| | Claim | Strength |
|---|---|---|
| **A** | No answer from Genie alone cites a governed business definition, because none exists in the lakehouse. | **Load-bearing. Cannot fail.** True by construction, every run, forever. |
| **B** | The answers Genie alone gives vary across runs. | **Vivid. Likely, not guaranteed.** Show it live, never depend on it. |

**Never build a beat on B alone.** If Genie answers the same way three times on stage, the beat
costs nothing: it is still an answer anchored to nothing, and the presenter says so and moves on.

**Corollary, and the reason this demo kept getting rewritten:** we do not predict what Genie
answers. Genie alone is generative and stochastic. Chasing a specific predicted answer, and then
engineering data so that answer is wrong, is unwinnable. No beat in this demo contains a scripted
answer for Genie alone.

**The corollary is unchanged by section 1's revision, and the order of operations is why.** Section
1 now allows reporting that an answer from Genie alone is false at full depth. That permission is about
recording what a probe found, after asking. It grants nothing to a document written before the ask.
Writing down the answer you expect is still banned whether you expect it to be right or wrong, and a
wrong answer you predicted is worth less than no answer at all, because you will read the transcript
looking for it. Probe, record, then write.

Anything a probe finds enters as Claim B unless repeated asking shows otherwise. That includes
findings that are flattering.

---

## 3. The two engines

**Genie alone.** The existing Databricks Genie Spaces product, Genie Agent. Natural language over Unity
Catalog. Scoped to the `supplier_risk` schema. Gets **every** instance table, including
`supply_relationships` and `owned_by`. Knowledge store holds column descriptions and join hints
only. No traversal, no graph algorithms, no authored business vocabulary.

**Genie + Graph.** The enterprise chat agent, Genie One. Wraps that same Genie space and adds MCP tools,
including a read-only Neo4j MCP server over the knowledge graph, plus the authored ontology of
terms, rules, thresholds, and metrics.

**These two names replace Run A and Run B, which this file used until 2026-07-19.** The rename is
vocabulary only and changes no settled line. Run A is Genie alone, Run B is Genie + Graph. The
worklog and the probe records keep the old names, because they are historical records and are
allowed to be stale.

**Fairness rule, non-negotiable:** both engines get every table. Nothing is withheld. The gap is
grounding, not access. No graph output is ever synced back into Delta.

---

## 4. The three steps of Beat 3

The graph grounds the answer through exactly three capabilities. They are named **Definition**,
**Discovery**, and **Explanation**, they appear in that order, and each produces its own visible
output in Beat 3. Refer to them by name and never by number: Beat numbers are the only numbered
sequence in this demo, and a second one next to them is what made the script hard to read.

| Step | Capability | What it does here |
|---|---|---|
| **Definition** | Ontology | What does "Critical Supplier" mean? RULE-05 says. The lakehouse has no answer to that question at all. |
| **Discovery** | Graph algorithms | Which entities satisfy that definition? Betweenness and the governed threshold return the Critical Supplier cohort, Cascade among them, with nobody pointing at it. Cascade is not the top of the ranking, so no score sort finds it. |
| **Explanation** | Pattern matching | Why Cascade out of the cohort? The Americas container-glass processors all draw their raw glass from one upstream furnace, Cascade. That convergence is what singles it out. |

**The honest caveat, said out loud:** once someone knows to start from the tier-1 suppliers,
"which supplier feeds all of these" is a single join, and Genie alone will write it. The graph-native
step is the one before it, knowing which suppliers to ask about. **Invite that question on stage
rather than hoping nobody asks it.**

**What the re-probe observed, and how many times.** The caveat was written while Cascade sat one hop
from the bottle makers, and it recorded that Genie alone wrote a correct convergence query on the
first try. That record no longer describes the live build. With the processor tier in between, the
invited convergence question was asked in five fresh conversations and Genie alone wrote a different
query every time: a boolean CASE, a filter that returned zero rows, a ranked list carrying a
supplies-all flag, and a listing of overlaps greater than one. Every one of the five stayed at a
single hop, so every one of them landed on the processors rather than on the furnace, and all five
concluded that no common upstream supplier exists. The graph, traversing the commodity-carrying
chain, returns yes and names the supplier.

**How that classifies, under section 2.** The load-bearing half is Claim A and it held: no run cited
a governed business definition, because there is none in the lakehouse to cite. The stability of the
conclusion is Claim B. The query was generative while the answer was not, which is the strongest
shape this evidence could take, and it is still five asks against one build rather than a guarantee.
So no beat may depend on Genie alone answering that way, and Beat 3 has to play unchanged if the
next ask comes back the other way. Section 1 governs the narration: describe the mechanism, that
Genie looks one level deep by default and could likely be prompted deeper, and never the verdict.

The caveat's underlying point survives all of this intact. Convergence is cheap in SQL once you know
where to start, and knowing where to start is what the graph contributes. What was removed is
"confirmed, not theoretical," which asserted a reliable behaviour that the re-probe does not
support.

---

## 5. The five beats

| # | Beat | Engine | What happens |
|---|---|---|---|
| 1 | Ask | Both | The diversification question, asked identically of both. |
| 2 | Ungrounded | Genie alone | Asked three times live, in fresh conversations. |
| 3 | Grounded | Genie + Graph | Definition, then Discovery, then Explanation. Names Cascade. |
| 4 | Exposure | Genie + Graph, routing to the lakehouse | The graph hands over attribution, the lakehouse computes revenue. |
| 5 | Decision | Room | A second source that also traces to Cascade changes nothing. |

**Beat 2 is live and repeated, with no scripted answer.** Ask, read what comes back, and note out
loud that nothing in it references a governed definition. If the answers differ across runs, narrate
the spread. If they do not, narrate the ungroundedness. Both land.

**Three asks, not two.** The Phase 0 spread measurement returned four distinct queries across five
runs, but two of the five were identical to each other. Two asks can therefore land on the same
axis and show no visible spread. Three is the better odds. Do not ask a fourth to manufacture a
disagreement: if three agree, narrate the ungroundedness and move on, per claim B.

**Beat 1's ambiguity is a feature, not a bug to fix.** The probe found Genie reading "diversified"
as units-per-supplier when the business meant sources-per-unit. Nothing in the lakehouse says which
axis is correct, and that is exactly the demonstration. Do not "fix" the question to force the
intended axis.

**Beat 3 includes the criticality side-by-side.** Ask "what is our single biggest point of failure
in our supply base?" of both engines. This is safe because we no longer depend on Genie alone's answer being
any particular thing.

**Beat 4 states the causal step out loud:** you cannot ship a bottled product without bottles, so if
the furnace stops, that unit's revenue stops rather than degrades, while the other four keep
shipping. The kicker: what you pay Cascade is a rounding error in procurement spend. The exposure is
the revenue that stops when they do, not what you pay them.

**Steering Genie + Graph is allowed. Scripting it is not.** Decided before the Genie + Graph probe, so the result
cannot argue us into either position after the fact. The presenter may ask a question that points at
the graph, name the ontology, or ask what a Critical Supplier is, because a risk committee would ask
exactly that and a demo of a knowledge layer is allowed to use the knowledge layer. The presenter may
not know the answer in advance. If the probe shows Genie + Graph needs steering to reach the definition, that
is a staging note for Beat 3 and nothing more. If it shows Genie + Graph never reaches the graph at all, that
is a routing defect and it is the one Genie + Graph result that stops the demo.

---

## 6. Frozen question text

Asked verbatim. Changing these requires changing this file.

**Beat 1, to both engines:**

```
How diversified is our glass bottle supply for the Americas?
```

**Beat 3, to both engines, the criticality side-by-side:**

```
What is our single biggest point of failure in our supply base?
```

**Beat 3 convergence, to Genie + Graph, the question that lands Cascade:**

```
Every container-glass processor that serves our Americas bottle makers buys its raw glass from somewhere. Is there a single upstream supplier they all depend on for it?
```

This is the Explanation step's question. The commodity-root re-probe asked it in four fresh
conversations and Genie + Graph named Cascade Glassworks as the single upstream source every time,
mostly with shallow queries rather than deep traversals. It is scoped to the processors' shared
upstream on purpose. Scoped to the bottle makers instead, the shared upstream is the processor tier
one hop up. Asked for the "source" or the "bottom" of the chain, the answer slides below the furnace
into the feedstock of cullet, sand and soda ash. Only the processor-scoped form lands on Cascade and
stops there.

**The danger words are "depend on" and "common upstream."** Not "point of failure," which is safe
and was probed. Beat 1 must never drift toward dependency phrasing. Those same words are the
intended phrasing of the Beat 3 convergence question above, which is exactly why they are banned at
Beat 1: they belong to Beat 3's discovery, so using them earlier spends it.

**The original reason for that rule is superseded, and the rule stays for a better one.** It was
written to stop Beat 1 handing Genie alone the convergence query directly, on the belief that
dependency phrasing would produce the answer Beat 3 exists to reveal. The re-probe found otherwise.
Asked directly what the Americas glass bottle suppliers depend on, Genie alone wrote one hop and
returned the container glass processors, with Cascade absent from the result set, and no question in
the re-probe produced a recursive CTE, six questions for six. On this topology, dependency phrasing
does not reach the furnace.

The rule survives because Beat 1's job is to ask a diversification question and let the
ungroundedness show. Dependency phrasing changes the subject to Beat 3's question, and the arc
collapses whichever way Genie alone answers it: reach the furnace and Beat 3 has no discovery left to
make, miss it and the room watches the same question asked twice. That reason is structural and holds
on every run, where the old one was a Claim B observation wearing a rule's clothing. It is also why
the rule does not get relaxed if a later probe shows Genie going deeper. The one-hop ceiling is
something we have observed repeatedly, not something we are owed.

**Beat 4, to the lakehouse:** recognized revenue per business unit for the most recent full quarter.
Exact wording pinned during the re-probe phase.

---

## 7. Asserted at build time

These are the premise, not the finding. Facts are asserted, outcomes are read.

- One business unit's glass bottle suppliers all trace to Cascade through commodity-carrying paths.
- Every other business unit has at least one glass supplier that does not trace to Cascade.
- The commodity-scoped exposure measure returns that one unit and no other.
- Cascade has zero direct `supplier_business_units` rows.
- The network is one connected component.
- Cascade is not the top-degree supplier. Cascade sitting one tier back from the bottle makers is
  the definition of a hidden choke point, so this is a property of an honest topology, not a plant.
  Keep it, since it is cheap and reflexes shift with model updates, but note it is **not** the last
  line of defense: the probe showed Genie does not reach for connection counts at all.
- **Each of Beat 3's three steps resolves.** RULE-05's text is retrievable, Cascade's node carries a
  betweenness property, and the convergence traversal returns at least one path. This is the
  mechanical half. That the three produce *distinct visible output on stage* cannot be asserted by a
  build and is a re-probe phase exit check instead.
- **No governed vocabulary is visible to Genie alone.** No table name, column name, table comment, column
  comment, Genie space instruction, or example SQL contains a governed term name, rule name, or a
  `TERM-`, `RULE-`, `MEAS-`, `THR-` or `GM-` identifier. This is the assert that protects claim A.
- **The supplier network is not a forest.** On a forest every centrality collapses to degree, which
  is the failure diagnosed in `london-bridge-is-falling.md`. Assert the edge count exceeds nodes
  minus components, that a substantial share of suppliers appear on both sides of
  `supply_relationships`, and that traversal depth reaches at least four tiers.

**A mechanical check cannot catch a paraphrase.** The vocabulary assert catches literal leaks. A
comment that describes what a Critical Supplier is without using the words passes it and still
breaks the demo. The editorial rule in `upload.py` stays as the human review for that, and the two
are not interchangeable.

**The actual last line of defense is the one-hop ceiling.** The re-probe phase asked ten questions
across six phrasings against the rebuilt data, where Cascade sits two tiers back behind the
container glass processors, and Genie alone never wrote a recursive CTE and never walked past one
hop, including on questions phrased with "depend on" and "upstream." The dependency question now
returns the processors and Cascade never appears. This is a repeated observation and not a
guarantee, so it is read the way section 1 reads the convergence result: probed, clean so far, and
not something a beat may lean on as if the next ask were bound by it.

**Read from the output, never asserted:** Cascade's betweenness rank, the shape of the betweenness
distribution, and which supplier a degree count names. The rank correlation between betweenness and
degree is printed to the build log every run and never asserted. Reading it is how drift gets
noticed. Asserting it is how data gets fitted to the story.

**THR-03** is a hand-set percentile of supply betweenness, fixed before the run. The build asserts
Cascade **clears** it, which is cohort membership, not rank.

**The percentile is immovable.** It is committed to git in its own commit, before the topology work
lands, so "chosen before the run" is a verifiable fact rather than a claim in a document. If Cascade
fails to clear it, the topology gets fixed and the percentile does not move.

**The stopping rule, so that "fix the topology" is not an unbounded tuning loop.** The distinction
that keeps this honest is that tuning data so an algorithm output lands a specific way is banned,
while building a topology in which a structural business premise is true is the work. If the
sole-source premise genuinely holds and Cascade genuinely sits in a structural hole, high betweenness
follows as a consequence rather than as a target. So:

- Cascade's betweenness percentile is logged on every build, from the first.
- **Two honest topology iterations, maximum.**
- If it fails twice, the diagnostic that matters is whether the sole-source assert passes. If
  sole-source passes and betweenness still does not clear, the conclusion is that betweenness is not
  measuring what the Discovery step claims it measures on this network. That is a real finding about the demo's
  design. Stop and escalate. Do not take a third run at the topology.

**The same stopping rule governs `MIN_INTERMEDIATE_FRACTION`,** the floor on how many suppliers appear
on both sides of `supply_relationships`. It is a tripwire against star-forest collapse, not a dial.
Two honest topology iterations, then escalate. The constant does not move, because a fraction that
gets loosened until the topology clears it is measuring nothing.

**The cohort must have more than one member.** A threshold that exactly one entity clears is a
post-hoc threshold no matter how it was derived. This is not the banned minimum-cohort clause, which
required a size in order to make a story work. This is its inverse: it forbids the one-winner shape.

---

## 8. Banned, permanently

Every item was a real failure in a previous pass.

- **Predicting Genie's answer, in any document or beat.** See section 2. Section 1 permits reporting
  that an observed answer is false at full depth. It does not permit writing down an expected answer
  of either kind before the ask.
- **Engineering data so a predicted Genie alone answer fails.** This is the sharp edge of the item above
  and it survives section 1's revision intact. A wrong answer that emerged from a topology built for
  other reasons is evidence. The same wrong answer produced by changing the topology until Genie alone
  missed is a plant, and no amount of accurate reporting afterwards converts one into the other.
- **Framing any beat as Genie being wrong, bad, or beaten.** Section 1 allows the result and governs
  the narration: describe the mechanism, that Genie looks one level deep by default and could likely
  be prompted deeper, and never the verdict.
- Decoy hubs, barring background suppliers from a business unit, reserving a subcategory for one
  supplier.
- Asserting the narrative in the generator. Build a true topology, run it, write the beats from the
  output.
- Post-hoc thresholds computed so exactly one entity clears them.
- **Quoting any value that a reseed would change.** No counts, scores, totals, currency figures, or
  resolved threshold values in prose, in the generator's narrative, in beat scripts, or in diagram
  labels. The numbers belong on screen at demo time. See section 9.
- Syncing GDS scores or graph classifications into gold tables.
- Withholding rows from Genie alone.
- A supplier spend column.
- Running GDS live on stage. The property is precomputed.
- Community detection. Louvain is dropped permanently; reasoning is archived in
  `simplified-plan.md`.
- **Redesigning Story 2.** Its numbers move when the data regenerates, which is expected and fine.
  Its structural asserts must still pass. "Do not touch Story 2" never meant its bytes would hold
  still.

**Out of scope, not open:** Databricks Genie Ontology is not enabled and has not been evaluated.
Nothing in this demo depends on it and nothing in this demo attacks it. Recorded here so it is not
reopened as a question.

**Also out of scope, not open:** the Genie + Graph plumbing. The operator has already stood up the Neo4j MCP
server with schema discovery and read-only Cypher support, and the Genie space alongside it, per the
"Genie space and MCP setup" section of `DEMO.md`. No phase builds, configures, or changes it. What
remains is verification only: Beat 3's three steps must be shown to resolve against the loaded graph, and
Genie + Graph must be probed and recorded. Recorded here so MCP setup is not reopened as work.

---

## 9. Reseed invariance

No demo artifact contains a value that a reseed would change. The data generator is RNG-driven and
Genie alone is stochastic, so any demo built on a specific figure is a demo waiting to break.

**What stays pinned:** protagonist identifiers and names, the governed vocabulary, the business unit
roster, and the structural facts in section 7. The five business units are a hardcoded literal in the
generator and do not move with the seed, so "the other four keep shipping" is a structural fact and
not a quoted figure.

**What moves freely:** every count, score, total, currency figure, and resolved threshold value.

**The as-of date is a third category, neither seeded nor pinned.** It is `date.today()` at
generation, by design, so the data always looks fresh. That means Beat 4's quarter is derived from
the build date, and if a calendar quarter rolls between the build and the demo, "the most recent full
quarter" means a different quarter than the one the data was shaped and asserted around. A pre-flight
check confirms the current quarter still matches the build's quarter and fails loudly if it has
rolled. The fix when it fails is a regenerate.

**Every assert states a relationship, never a value.** Not "betweenness above a constant" but "at or
above the percentile." Not "five glass suppliers" but "all of this unit's glass suppliers trace to
Cascade."

**The honest version of this rule:** the demo is not reseed-invariant because nothing depends on the
data. It is reseed-invariant because the structural asserts fail loudly when a reseed breaks a
premise. Reseed and a business unit might stop being sole-sourced. The asserts are what make "it
does not matter if the data reshuffles" true rather than hopeful. Do not read this section as
licence to delete them.

**Enforcement is editorial, not tooled.** Whoever changes a doc re-reads it for reseed-variant
values before committing. No build target polices prose.

---

## 10. Open, pending evidence

Nothing here is decided by argument. Each closes with a transcript or a build output.

| Item | Closes in | How |
|---|---|---|
| Beat 4's exact question wording | The re-probe phase | Asked verbatim, confirmed not steered |
| The Story 1 beat script | The re-probe phase | Written from betweenness output, never before |

**Closed 2026-07-19, whether Genie recurses once Cascade is two tiers back.** Recorded in
`probe-run-a-v3.md`. Ten questions across six phrasings against the rebuilt data, with Cascade two
tiers back behind the container glass processors. No recursive CTE anywhere and no walk past one
hop, including on "depend on" and "upstream" phrasings. The dependency question returns the
processors and Cascade never appears. Closed as evidence for the one-hop ceiling as Claim B, not as
a guarantee about future asks.

**Closed 2026-07-19, the spread of Genie alone answers to Beat 1.** Five fresh conversations, recorded in
`probe-run-a.md`. Four distinct queries, verdicts spanning "not diversified" to "highly
diversified" on identical data. Claim A held five for five, no answer cited a governed definition.
The one-hop ceiling held five for five. Two of the five runs agreed with each other, which is why
this closes as evidence for claim B and not as a promotion of it.

**Already verified, no work needed.** The `upload.py` `supply_relationships` table comment is
already the neutral version, and no Genie space example SQL touches that table. Both re-verify
after the rebuild rather than being rewritten.

**"Done" must name the check that proves it.** Twice in this project's history a change recorded in
the worklog as applied and verified was absent from the live workspace, and one of those root causes
was never found. So a claim of done cites the assert or the read-back query that demonstrates it.
Without one, the correct word is "believed done." Verification means reading state back from the
live system, never that the statement was issued.

**The escape hatch is closed, with no exceptions.** "If Genie alone does better than expected, adjust the
script" is not a resolution and no longer appears anywhere. There is no expected answer to do better
than.

**Including the last one.** An earlier draft kept a single carve-out: Genie alone naming Cascade unprompted
at Beat 1 meant fixing the topology rather than the beat. Deleted 2026-07-19. It was the old
predict-and-defeat reflex surviving in one line, and it does not survive the grounding claim, because
Genie can name Cascade and still cite no governed definition. The cost is one line of Beat 3 staging,
answered by leading with the definition leg instead of the discovery leg. **The data is rebuilt only
when a structural assert fails, never because of something Genie said.**
