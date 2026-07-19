# Story 1 demo contract

This is the locked short form. It is the authority. `simplified-plan.md` is the working detail
behind it, and where the two disagree, this file wins.

**Rule for changing this file:** anything here is settled. Reopening an item requires saying which
line is wrong and why, not restating a preference. If a proposal does not change a line below, it
is a detail and belongs in `simplified-plan.md`.

---

## 1. The claim

The demo is **ungrounded versus grounded**. It is not wrong versus right.

> Genie Agent is a frontier LLM over tables. Ask it a business question and it returns a plausible
> answer grounded in nothing but column names. The axis it picks is generative and not
> reproducible. Genie One with the graph ontology returns an answer grounded in an authored
> definition, so it is the same answer every time and a risk committee can act on it.

Supporting statements, both still true and both still used on stage:

> The graph finds the attribution. The lakehouse computes the number.

> Run A can compute any number you ask for, perfectly, and still not know which number to ask for.

**What this claim is not.** It is not "SQL cannot express traversal or centrality." SQL can express
both. It is not "Run A is wrong." Run A is never wrong and is never beaten. Its answers are
plausible, defensible, and anchored to nothing.

**What keeps the claim true.** It holds by construction only while no authored artifact is visible
to Run A. The governed vocabulary, meaning the term names, the rule names, and the `TERM-`,
`RULE-`, `MEAS-`, `THR-` and `GM-` identifiers, must never appear in a Unity Catalog table or
column name, a table or column comment, a Genie space instruction, or an example SQL. Section 7
asserts this. Genie inventing a plausible-sounding definition is not a failure of the claim: an
invented definition cites nothing, which is the demonstration.

---

## 2. The two-claim rule

This is the most important operating rule in the demo. Two claims, different strength. Keeping them
separate is what stops this from being relitigated.

| | Claim | Strength |
|---|---|---|
| **A** | No Run A answer cites a governed business definition, because none exists in the lakehouse. | **Load-bearing. Cannot fail.** True by construction, every run, forever. |
| **B** | Run A's answers vary across runs. | **Vivid. Likely, not guaranteed.** Show it live, never depend on it. |

**Never build a beat on B alone.** If Genie answers the same way three times on stage, the beat
costs nothing: it is still an answer anchored to nothing, and the presenter says so and moves on.

**Corollary, and the reason this demo kept getting rewritten:** we do not predict what Genie
answers. Genie Agent is generative and stochastic. Chasing a specific predicted answer, and then
engineering data so that answer is wrong, is unwinnable. No beat in this demo contains a scripted
Run A answer.

---

## 3. The two runs

**Run A, Genie Agent.** The existing Databricks Genie Spaces product. Natural language over Unity
Catalog. Scoped to the `supplier_risk` schema. Gets **every** instance table, including
`supply_relationships` and `owned_by`. Knowledge store holds column descriptions and join hints
only. No traversal, no graph algorithms, no authored business vocabulary.

**Run B, Genie One.** The enterprise chat agent. Wraps that same Genie Agent and adds MCP tools,
including a read-only Neo4j MCP server over the knowledge graph, plus the authored ontology of
terms, rules, thresholds, and metrics.

**Fairness rule, non-negotiable:** both runs get every table. Nothing is withheld. The gap is
grounding, not access. No graph output is ever synced back into Delta.

---

## 4. The three legs

The graph grounds the answer through exactly three capabilities. They appear in this order, and
each produces its own visible output in Beat 3.

| Leg | Role | What it does here |
|---|---|---|
| **Ontology** | **Definition** | What does "Critical Supplier" mean? RULE-05 says. The lakehouse has no answer to that question at all. |
| **Graph algorithms** | **Discovery** | Which entity satisfies that definition? Betweenness names Cascade Glassworks, with nobody pointing at it. |
| **Pattern matching** | **Explanation** | Why? Every Americas glass supplier converges on Cascade. |

**The honest caveat, said out loud:** once someone knows to start from the tier-1 suppliers,
"which supplier feeds all of these" is a single join, and Run A can get there. This is confirmed,
not theoretical: given the phrase "common upstream supplier," Genie wrote a correct convergence
query on the first try. The graph-native step is the one before it, knowing which suppliers to ask
about. **Invite that question on stage rather than hoping nobody asks it.** The question
presupposes the finding it returns, which is the point.

---

## 5. The five beats

| # | Beat | Run | What happens |
|---|---|---|---|
| 1 | Ask | Both | The diversification question, asked identically of both. |
| 2 | Ungrounded | A | Asked three times live, in fresh conversations. |
| 3 | Grounded | B | Definition, then discovery, then explanation. Names Cascade. |
| 4 | Exposure | B routing to lakehouse | The graph hands over attribution, the lakehouse computes revenue. |
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
in our supply base?" of both runs. This is safe because we no longer depend on Run A's answer being
any particular thing.

**Beat 4 states the causal step out loud:** you cannot ship a bottled product without bottles, so if
the furnace stops, that unit's revenue stops rather than degrades, while the other four keep
shipping. The kicker: what you pay Cascade is a rounding error in procurement spend. The exposure is
the revenue that stops when they do, not what you pay them.

**Steering Run B is allowed. Scripting it is not.** Decided before the Run B probe, so the result
cannot argue us into either position after the fact. The presenter may ask a question that points at
the graph, name the ontology, or ask what a Critical Supplier is, because a risk committee would ask
exactly that and a demo of a knowledge layer is allowed to use the knowledge layer. The presenter may
not know the answer in advance. If the probe shows Run B needs steering to reach the definition, that
is a staging note for Beat 3 and nothing more. If it shows Run B never reaches the graph at all, that
is a routing defect and it is the one Run B result that stops the demo.

---

## 6. Frozen question text

Asked verbatim. Changing these requires changing this file.

**Beat 1, to both runs:**

```
How diversified is our glass bottle supply for the Americas?
```

**Beat 3, to both runs:**

```
What is our single biggest point of failure in our supply base?
```

**The danger words are "depend on" and "common upstream."** Not "point of failure," which is safe
and was probed. Beat 1 must never drift toward dependency phrasing, because that hands Run A the
convergence query directly.

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
- **Each of the three legs resolves.** RULE-05's text is retrievable, Cascade's node carries a
  betweenness property, and the convergence traversal returns at least one path. This is the
  mechanical half. That the three produce *distinct visible output on stage* cannot be asserted by a
  build and is a re-probe phase exit check instead.
- **No governed vocabulary is visible to Run A.** No table name, column name, table comment, column
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

**The actual last line of defense is the one-hop ceiling.** Across four probed questions, Genie
never wrote a recursive CTE and never walked past one hop, including on a question phrased with
"depend on." Whether that holds once Cascade sits two tiers back is the single most important
thing to learn from the re-probe phase.

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
  measuring what leg 2 claims it measures on this network. That is a real finding about the demo's
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

- **Predicting Genie's answer, in any document or beat.** See section 2.
- Decoy hubs, barring background suppliers from a business unit, reserving a subcategory for one
  supplier.
- Asserting the narrative in the generator. Build a true topology, run it, write the beats from the
  output.
- Post-hoc thresholds computed so exactly one entity clears them.
- **Quoting any value that a reseed would change.** No counts, scores, totals, currency figures, or
  resolved threshold values in prose, in the generator's narrative, in beat scripts, or in diagram
  labels. The numbers belong on screen at demo time. See section 9.
- Syncing GDS scores or graph classifications into gold tables.
- Withholding rows from Run A.
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

**Also out of scope, not open:** the Run B plumbing. The operator has already stood up the Neo4j MCP
server with schema discovery and read-only Cypher support, and the Genie space alongside it, per the
"Genie space and MCP setup" section of `DEMO.md`. No phase builds, configures, or changes it. What
remains is verification only: the three legs must be shown to resolve against the loaded graph, and
Run B must be probed and recorded. Recorded here so MCP setup is not reopened as work.

---

## 9. Reseed invariance

No demo artifact contains a value that a reseed would change. The data generator is RNG-driven and
Genie Agent is stochastic, so any demo built on a specific figure is a demo waiting to break.

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
| Whether Genie recurses once Cascade is two tiers back | The re-probe phase | All four questions re-asked |
| Beat 4's exact question wording | The re-probe phase | Asked verbatim, confirmed not steered |
| The Story 1 beat script | The re-probe phase | Written from betweenness output, never before |

**Closed 2026-07-19, the spread of Run A answers to Beat 1.** Five fresh conversations, recorded in
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

**The escape hatch is closed, with no exceptions.** "If Run A does better than expected, adjust the
script" is not a resolution and no longer appears anywhere. There is no expected answer to do better
than.

**Including the last one.** An earlier draft kept a single carve-out: Run A naming Cascade unprompted
at Beat 1 meant fixing the topology rather than the beat. Deleted 2026-07-19. It was the old
predict-and-defeat reflex surviving in one line, and it does not survive the grounding claim, because
Genie can name Cascade and still cite no governed definition. The cost is one line of Beat 3 staging,
answered by leading with the definition leg instead of the discovery leg. **The data is rebuilt only
when a structural assert fails, never because of something Genie said.**
