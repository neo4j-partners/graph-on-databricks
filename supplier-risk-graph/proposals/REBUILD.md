# Rebuild work list

The topology rebuild and everything downstream of it. Delete this file when it is done, after moving
the pre-flight section to `DEMO.md`, since those two checks run on every demo day and not once.

`proposals/CONTRACT.md` still holds the standing rules. This file holds only what is left to do.

## Status

Guards are landed and green and the routing gate is cleared, so nothing in this section is open.
`guard.py`, the three-legs check, the quarter assert, the Story 2 landmine asserts, and now the three
structural asserts.

### Session status, 2026-07-19

The rebuild and the re-probe are done and Story 1's logic is settled: Cascade stays the protagonist,
and the wording that lands it is locked. What remains is one hands-on-the-space re-sync, one clean
regenerate, and the transcript-driven writing.

Landed this session, beyond the boxes below:

- **Beat 3's landing wording is settled and locked.** The commodity-root re-probe found that a
  question scoped to the container-glass processors' shared upstream names Cascade on every run,
  while "source" and "bottom" framings slide below it into the feedstock. That verbatim question is
  now frozen in `CONTRACT.md` section 6, and section 4's Discovery row no longer claims betweenness
  names Cascade, because it names the cohort. See "The commodity-root re-probe" below.
- **The classification asymmetry is half closed.** Critical Supplier is now written as
  `CLASSIFIED_AS` edges by `gds.py` from the governed threshold, simulating a production batch job,
  with the cohort derived rather than named. Ownership Risk still carries none, a known defect
  belonging to Story 2. The docs claiming the two graph-native terms are never planted were corrected
  in `DEMO.md`, `README.md`, `upload.py`, and `load.py`.
- **A fairness defect was found and the docs fixed, the live space still owes the change.** The Genie
  space is missing `compliance_findings` and `owned_by`, which `CONTRACT.md` section 3 requires both
  engines to have. The docs across `README.md`, `DATA_ARCHITECTURE.md`, and `DEMO.md` now say both
  are in. The live re-sync and the fanout guard it needs are folded into the Genie space item below.
- **`guard.py` now scans row values** of the tables attached to the space, closing the hole where a
  governed term name sitting in a column like `classifications.term` passed a guard that only read
  `information_schema`. The commodity scan is deliberately not run over row values, since a single
  commodity member is instance data.
- **The seed is locked in the docs.** `SEED = 42` is fixed and `make demo` cannot change it, because
  the generator has no seed flag. The generator, `README.md`, and `DEMO.md` now warn that editing the
  seed is a reseed that moves rankings, not a refresh.
- **`CONTRACT.md` sections 1, 4, 6, 7, and 10 were brought current** with what the re-probe found,
  and the probe harness was rebuilt to write an audited, per-turn-flushed log.

Remaining, in order:

- **The live Genie space re-sync,** the one hands-on-the-workspace task, now also adding the two
  tables and the fanout instruction. Folded into the Genie space item below.
- **One clean `make demo`,** because `classifications` is stale from a standalone `gds.py` run.
- **The transcript-driven writing,** which waits on a captured Genie + Graph transcript: the five
  beats, the three-distinct-outputs check, the Beat 4 five-unit rewrite, the Story 1 diagram, and
  archiving the old transcript PDFs.

- [x] **The three structural asserts. Landed, and they were missing rather than green.** An earlier
      version of this line recorded them as landed alongside the other four. They were not in the
      code: no forest check, no intermediate-share check, no depth check, and no
      `MIN_INTERMEDIATE_FRACTION` for the stopping rule to govern, which is the failure mode
      `CONTRACT.md` section 7 exists to catch. They are now `check_supply_structure` in
      `generate_data.py`, called from `main` ahead of `check_story1`, with
      `MIN_INTERMEDIATE_FRACTION` and `MIN_SUPPLY_TIERS` sitting with the other
      governed constants. All three pass against the pre-rebuild build and the realized figures print
      to the build log every run rather than being asserted.
- [x] **The depth leg was unfalsifiable when it landed, and has been rebuilt.** The original probe
      backtracked over simple paths and returned `MAX_PROBE_TIERS` the moment it popped any walk that
      long, so it saturated on the first node scanned and printed `12+` as though that were a
      measurement. A floor over a saturating measure passes unconditionally, so the leg was reporting
      green rather than checking anything. It is now `supply_depth` in `generate_data.py`, the longest
      directed shortest-path chain, measured by one breadth-first sweep per node. `MAX_PROBE_TIERS` is
      deleted rather than left as a dead constant. The same data that printed `12+` now measures 23
      tiers, which is the clearest evidence that the old figure was a saturation marker.
- **What the rebuilt depth leg does not do, stated so it is not over-trusted.** It counts reachability
  chains, and a cycle inflates those. A flat two-tier trading cluster with no supply tiers at all
  clears `MIN_SUPPLY_TIERS` once a couple of back-edges exist, so the measure is a tripwire against
  outright flattening rather than a reading of how many tiers the network runs. On a pure flat network
  the intermediate-share leg fires first, so the depth leg only discriminates on a network that is flat
  and already above the intermediate floor. Its docstring claims the measure never overstates depth,
  which is true of path existence and not of tier count.
- **Green here does not mean the topology is healthy, and the margins are the reason to say so.** All
  three clear comfortably on the build whose betweenness is trivially maximal because Cascade is a cut
  vertex. They catch star-forest collapse and nothing else, so the rebuild has to keep clearing them
  while fixing what they cannot see. The depth floor will not bind during the rebuild, and now that
  the leg measures rather than saturates that is a real margin rather than an artifact. The
  intermediate share is far enough above its floor that a failure there would signal something badly
  wrong rather than a near miss.
- **The RNG stream is unmoved, verified rather than assumed.** The regenerate came back byte-identical
  across every CSV except the resolved threshold values, which the generator emits empty and `gds.py`
  writes back, so the pre-rebuild baseline still stands.

- [x] **Run B routing probe. Done, and the gate is cleared: routing is not a defect.** Run B is the
      MAS serving endpoint, which carries the Story 1 Genie space, the Neo4j MCP tools, and a Python
      exec tool. Beat 3, asked verbatim, went to Genie first and then made repeated
      `read_neo4j_cypher` calls that returned rows from the loaded graph, including a
      `CLASSIFIED_AS` traversal to a `BusinessTerm` node and a `SUPPLIES` traversal to business
      units. Definition-first resolution was observed rather than assumed. Beat 1, asked verbatim in
      two fresh invocations, produced only Genie calls and never reached the graph. That is the
      designed behavior, not a fault: `CONTRACT.md` section 5 makes Beat 1 the "Ask" beat put to both
      runs, makes its ambiguity the demonstration, and has Beat 4 route Run B to the lakehouse on
      purpose. The beat that must be grounded is grounded.
- **Two staging facts recorded with it.** Every Neo4j call arrives as an approval request and the
  endpoint blocks until it is answered, so whoever drives Beat 3 approves several tool calls
  mid-answer, and whether the UI prompts or auto-approves is unestablished. Separately, registration
  of the Python exec tool failed intermittently with `INVALID_PARAMETER_VALUE` and killed the whole
  turn when it did. Neither blocks the rebuild. Both belong in a dry run.
- **`guard.py` was run live after the probe and is clean,** across Unity Catalog tables and columns,
  the full Genie space definition, and the banned gold tables parsed out of the space's data sources.
  The live space still carries an auto-generated description rather than the authored one, which is a
  priming problem and not a vocabulary leak. `DEMO.md` now says what to put in both the description
  and the instructions fields.

## The rebuild

One regenerate cycle, run repeatedly until clean. The generator changes, the GDS changes, `make
demo`, `make expected`. Do not try to split it into stages.

**Precondition: a clean tree.** The guards land as commits before the first
regenerate runs. `worklog/lessons-learned.md` records a regenerate on a dirty tree destroying
uncommitted data, and this is one long regenerate loop, so the rule is stated here rather than
remembered. It is also not a one-time check: the loop below regenerates repeatedly, so commit
between iterations and re-read this line each time rather than treating it as closed.

**The stopping rule governs this whole section.** `CONTRACT.md` section 7 holds it: two honest
topology iterations, the percentile does not move, and `MIN_INTERMEDIATE_FRACTION` is a tripwire
rather than a dial. It is repeated as a pointer because the loop below is exactly where it gets
violated. If Cascade fails to clear THR-03 twice, check whether the sole-source assert passes and
escalate. Do not take a third run at the topology.

### Iteration 1: built, run, and green, with one defect that is not the topology's

The generator and the GDS are rebuilt and `make demo` runs clean end to end. What it produced:

- **Cascade clears THR-03, which was the open empirical question.** The percentile resolved to a
  cutoff catching a cohort of eight, and Cascade is in it. The cohort has more than one member
  without anything being arranged for it.
- **The three legs intersect on exactly one supplier, and it is not the one any ranking returns.**
  Cascade ranks eighth of 169 on raw betweenness. Of the eight in the cohort, it is the only one
  sitting on a commodity-carrying glass path into the Americas. So the finding comes from the
  definition and the commodity scoping together, and no single ordering produces it. That is a
  better demo than Cascade topping the ranking would have been, and it was not designed for.
- **A rival furnace clears the threshold on its own merits.** Raw glass returns a cohort of furnaces
  and one of them is genuinely critical elsewhere, which is what the subcategory was supposed to
  stop being a synonym for the protagonist.
- **Cascade is not a cut vertex.** Removing it strands nobody. The network holds at one component,
  73 percent intermediate, 26 tiers deep.
- **The premise assert earned its place on the first run.** It failed, and it failed on something no
  other check would have seen: the feedstock vendors were buying from unfiltered cluster members, so
  a background furnace could sell to a vendor that sells to Cascade, and the Americas' glass became
  reachable from furnaces other than Cascade by running the path backwards through the feedstock
  tier. Vendors now buy from the non-glass side of their cluster, which is also what a cullet
  recovery operation actually does.

**The defect, and it belongs to a choice made during the rebuild rather than to the agreed
topology.** Deleting the decoy-hub loop left nothing producing a degree leader, so the clusters were
changed to grow by preferential attachment. That produced a real leader, and it also correlated the
two measures: six of the top eight by betweenness are also the top eight by degree, and Cascade sits
at rank eight on both. Leg 2 claims betweenness discovers what counting connections cannot, and on
this build counting connections over `supply_relationships` returns Cascade too. The
`top_by_degree != CASCADE_ID` assert passes, so nothing caught it; what failed is the claim that
assert stands in for, not the assert.

**The fix is density, not attachment, and it keeps both mechanisms.** Preferential attachment stays,
because without it the degree distribution is flat enough that the leader and Cascade sit within a
hair of each other, which is a coin toss on stage. `SUP_WEB_CHORD_RATIO` rises alongside it. Chords
are the only mechanism here that makes a well-connected supplier uncritical: they give a cluster hub
alternate routes so traffic passes around it, which leaves its degree intact and collapses its
betweenness. Cascade is untouched by them because no chord exists around its position, and lowering
background betweenness lowers the percentile, so it clears with more headroom rather than less.

**This is not asserted, and that is deliberate.** The realized top-N overlap prints alongside the
degree leader line. `check_supply_structure` already draws this line: it asserts the structure in
which betweenness and degree *can* diverge and refuses to assert that they *do*, because asserting
the outcome is fitting the data to the story. A build where the separation does not appear at a
plausible density is a finding to escalate, not a reason to keep turning the ratio.

**Does this spend an iteration?** No, and the reasoning matters more than the answer. The stopping
rule counts honest attempts at the agreed topology. What failed here is an unrequested design choice
made inside that topology, and Cascade cleared the percentile on the first run, which is the thing
the rule exists to protect. Recording it here rather than deciding it silently is the point.

### The chord-ratio build: separation achieved, and one thing changed that was not the target

`SUP_WEB_CHORD_RATIO` went from 0.6 to 1.5, preferential attachment untouched. The reasoning is in
the constants block in the generator: below 1.0 most nodes get no chord and a tree-shaped backbone
survives, and on a tree the busiest node is on every path through its part of the network, so the
two measures agree by construction. Above 1.0 every node has more than one chord endpoint in
expectation. The value is a background density parameter and does not reach Cascade, whose score
comes from spanning the feedstock and processor tiers, where no chord routes around it.
`report_degree_overlap` in `gds.py` prints the realized overlap next to the degree leader line.

`make demo` re-run clean, and what it produced:

- **The separation appeared.** The top eight by each measure now share three suppliers rather than
  six, and Cascade is outside the top eight by degree entirely while ranking eighth by betweenness.
  A GROUP BY over `supply_relationships` does not return it. Leg 2's claim now holds on the data
  and not just on the topology.
- **Cascade still clears THR-03, in a cohort of eight, with the cutoff lower than before.** That is
  the predicted side effect: suppressing background betweenness lowers the percentile, so Cascade
  clears with more headroom rather than less.
- **The sole-source premise holds.** The rival furnace in the cohort carries no commodity-carrying
  glass path into the Americas, so it is critical elsewhere on its own merits, which is what the
  subcategory was supposed to do.
- **The degree leader and the betweenness leader are now the same supplier.** Worth noting and not a
  problem: what the demo needs is that the leader is not Cascade, and it is not.

**What changed that was not the target, and it should not be fixed quietly.** The intersection is no
longer exactly one supplier. The processor Cascade sells through rose into the THR-03 cohort, and it
sits on commodity-carrying glass paths into the Americas too, so the cohort now contains two glass
suppliers on the Americas' chain rather than one. The iteration 1 bullet claiming exactly one
supplier is superseded by this section.

Whether that weakens Story 1 is a judgement call and not mine to make silently. The case that it
does not: Cascade is the upstream one, every unit of the processor's material passes through it, and
a risk committee surfacing both is a more honest result than a threshold that isolates a single
name, which is the failure CONTRACT.md section 8 bans. The case that it does: Beat 3's punchline is
a name, and two names need a sentence explaining which one to act on. **Open for the re-probe to
settle**, because the right test is what Genie One actually returns when asked, not what the graph
could be made to return. Do not re-tune the topology for it before then.

### Topology, agreed

Cascade stops being the network's only bridge and becomes a genuine narrow waist: it buys feedstock
from vendors spread across the regional clusters and sells down through intermediate glass processors
to the five tier-1 bottle makers. It sits between a large upstream population and a large downstream
one and earns its betweenness by position rather than by being the single cut vertex.

**Why the buy side carries the fan-in, which is the load-bearing realism claim.** Betweenness on an
undirected projection is direction-blind, so fan-in and fan-out contribute identically to the score.
They are not equally true. Container glass is heavy and cheap to the point that shipping it any
distance costs more than it is worth, so melting and forming sit close together and a furnace selling
raw glass across regions is a shaky premise. A furnace buying cullet, sand and soda ash from vendors
across several regions is simply how furnaces work. Same topology, and the premise stands on its own
without the score needing it to. Cullet therefore belongs upstream as feedstock rather than between
the furnace and the bottle makers, which fixes the chain's direction and Cascade's fan-in in one edit.

**Measured before building, not after.** A throwaway simulation over the proposed shape, exact Brandes
on the undirected projection, many seeds per configuration. It touched no generator code, no CSV and
no graph, so it spent no part of the two-iteration budget. What it found:

| Question | Answer |
|---|---|
| Does cluster count decide whether Cascade clears? | No. Cascade fails to clear at every cluster count from two to six when it sits at the end of the chain. This was the number the first draft of this proposal argued about, and it was the wrong one. |
| What does decide it? | Cascade's fan-in across clusters, and it is a sharp threshold rather than a gradient. |
| Is Cascade still a cut vertex? | No, at every fan-in tested. Removing it leaves the network in one component. |
| Does chain depth change the score? | No. One processor tier and two behave the same, so depth is a staging decision. |

| Decision | Agreed | Why |
|---|---|---|
| Regional clusters | Four | Measured as not load-bearing for the score, so this is chosen for plausibility and for giving each cluster enough members to hold a real internal distribution. |
| Inter-cluster bridges | Six to eight, every one a different supplier | Covers most cluster pairs so no single supplier separates the graph. Distinct suppliers stop one bridge inheriting the score Cascade is being moved away from. |
| Bridge commodities | Freight, equipment and ingredients, never glass | Keeps the commodity-scoped exposure measure leak-free while the background stays structurally rich. |
| Cascade's feedstock fan-in | Six vendors, spread across the clusters | Four clears every seed and two clears fewer than half, so four sits close to the fragile edge. Six buys reseed headroom and is no less plausible for a furnace's feedstock base. |
| Intermediate processor tiers | One, unless the room needs the extra realism | Costs nothing in score either way, so it is decided on whether Beat 3's convergence stays legible on screen. |
| Rival furnaces | Three or four, feeding the other units' bottle makers | Makes the raw-glass subcategory return a real cohort, and makes the other four units genuinely protected rather than merely unlinked. |

**Ranking first by position is permitted. Ranking first by being the only bridge is not.** The
contract requires the cohort to have more than one member, and every configuration tested returned a
cohort with more than one member. `assert_betweenness` reports the ranking and does not assert who
wins. The original objection was never that Cascade ranks
first, it was that it ranked first *because it was the only bridge*, which is trivially true and
invites a fair question from the room. The cut-vertex test above is what separates those two, and it
is the check to re-run against the real build rather than trusting the simulation.

**The stopping rule still governs, and the simulation does not suspend it.** The model wired clusters
as a chain plus random chords, which is not the generator, so treat the ranks as directional and the
cut-vertex result as the robust finding. If the real build has Cascade below the percentile, the fix
must change which structural relationship is true. If the only available fix is nudging fan-in or
bridge counts until Cascade clears, that is the banned bar wearing new clothes: stop, report, and do
not spend the second iteration on it.

**`MIN_INTERMEDIATE_FRACTION` now exists,** with the floor `simplified-plan.md` intended, so the
stopping rule above governs a constant that is actually in the generator. It landed with the other two
structural asserts rather than waiting on this proposal, because a guard proven green on known-good
data is what makes a later failure unambiguously the data's fault rather than the check's.

### Generator, `make_supply_relationships`

Rebuild around one true fact: one business unit's tier-1 bottle suppliers all trace back through the
sub-tier to Cascade, and the other units' glass suppliers do not. That is the entire topology.

- [x] **Several regional clusters with multiple inter-cluster bridges,** not two clusters joined by
      one. Cascade is currently a literal cut vertex, which makes its betweenness trivially maximal
      and invites the fair question of why a global supply network has a single bridge.
- [x] **The extra bridges carry something other than glass.** More bridges make betweenness
      interesting and also give the exposure measure more places to leak. Commodity scoping is what
      keeps those compatible.
- [x] **The glass chain is a chain of glass companies.** Every sub-tier vendor between Cascade and
      the tier-1 bottle makers must itself trade in a glass subcategory, or the path is not
      commodity-carrying and the sole-source premise fails silently. What counts as a glass
      subcategory is defined by the `glass` entry in the generator's `COMMODITY_SUBCATEGORIES`, so
      every new intermediate subcategory added below goes into that entry in the same edit. Its
      comment block already anticipates this. Miss it and the new sub-tier vendors fail the commodity
      test, the paths from Cascade to the bottle makers stop being commodity-carrying, and the
      premise fails with no assert firing. Second-order consequence, worth knowing before it becomes
      a debugging session: `guard.py` reads that dict through its `commodity_subcategories` helper,
      so each new subcategory becomes newly scanned vocabulary and a comment or Genie instruction
      that enumerates two members of the glass grouping starts failing the guard. That is the
      intended behavior, not a regression.
- [x] **Real intermediate subcategories for the sub-tier,** not raw glass doing double duty as both
      Cascade's peers and its customers. Double duty breaks the cohort check, since `WHERE
      subcategory = 'raw glass'` is supposed to return other furnaces. The processor tier sits
      downstream of the furnace, so name it for what it makes, `container glass` being the obvious
      one. Cullet is not a candidate here: the agreed topology puts it upstream as feedstock, which
      is where it belongs physically and where it does the fan-in work.
- [x] **The feedstock tier is glass too, and it is easy to forget.** Cascade's feedstock vendors are
      what give it the fan-in the score depends on, so if they are not in `COMMODITY_SUBCATEGORIES`
      the paths through Cascade stop being commodity-carrying at exactly the point the story turns
      on. Cullet, sand and soda ash all belong in the `glass` entry alongside the processor tier.
- [x] **Keep the glass chain shallow.** Cascade to sub-tier to tier-1 to business unit, so Beat 3's
      convergence paths stay legible on screen. The four-tier assert is cleared by the background
      network, which is also what gives betweenness a real distribution.

**The premise and the banned bar, distinguished.** Constructing the sole-source premise means the
generator decides which glass suppliers the Americas draws from, and that code will look like the bar
being deleted below. The test: if an edit fixes a count, a score, or a predicted answer, it is the
bar wearing new clothes. If it fixes which structural relationship is true, it is the premise, and
building the premise is the work.

### Generator, delete

- [x] `SUP_HUB_DEGREE_MARGIN` and the decoy-hub boost loop. Leave SUP-109 as an ordinary supplier
      rather than removing the row, so downstream RNG draws do not shift for no benefit.
- [x] `CASCADE_A_LINKS` and `CASCADE_B_LINKS` as hand-tuned counts.
- [x] The `americas_glass == set(TIER1_IDS)` assert and the glass-bottle bar in `make_supplies`.
- [x] The "raw glass is reserved for Cascade" reservation, so the subcategory holds a cohort.
- [x] The rank-disagreement asserts, the `pairs_separated` strict-max assert, and the cut-vertex
      assert, which the connected-component check replaces.
- [x] **The BU-03 currency band in `check_exposure`,** which is pure surplus, because the recompute
      above it already confirms the figure sums the right unit, quarter, and column.
- [x] **The Jade band is replaced, not deleted.** It bracketed `JADE_CREDIT_FACILITY`, which `main`
      pins onto Jade's row and then derives `jade_exposure` from, so the band asserted a constant
      against a window drawn around that same constant and could not fail. `check_exposure` now takes
      `customers`, resolves Jade's row by `JADE_ID` itself, recomputes her exposure from the
      `creditLimit` column, and asserts the caller's figure against it. A fitted band gets replaced by
      a recomputation, not removed.
- **The recompute's reach is narrower than the BU-03 one, which is worth knowing before trusting it.**
  `jade` in `main` and Jade's row in `customers` are the same dict object, so the check catches a
  caller that reads the wrong customer or the wrong column and cannot catch a mutation between the pin
  and the derivation. `fit_credit_facilities` runs in that window and would move both sides
  identically. BU-03's recompute has the same property against `revenue_entries`. If an independent
  leg is ever wanted, the invoice-balance-inside-facility relation is the available source.

**The RNG stream will shift and there is no way around it.** Adding `raw glass` to the name-pool dict
adds an `rng.shuffle`, and adding it to `SUBCATEGORIES["packaging"]` changes an `rng.choice` from four
options to five. `make_suppliers` runs early off the shared `rng`, so the blast radius is every figure
in `ground_truth.json`, including Story 2. That is expected and fine. What must survive is the
structural asserts, and re-verifying them is part of this step.

### GDS

- [x] **Rework the THR-03 computation** to resolve the generator's `SUPPLY_CONCENTRATION_PERCENTILE`
      rather than compute a one-winner cutoff. The one-winner cutoff logic for Story 1 goes:
      `concentration_cutoff` is rewritten rather than deleted, and `place_cutoff` survives for
      Story 2. This closes the current disagreement where the graph states a governed percentile in
      THR-03's `basis` and computes its cutoff by another route.
- [x] **Delete the strict-max requirement in `assert_betweenness`.** Replace with the cohort check,
      that Cascade clears THR-03. Report the ranking, do not assert who wins.
- [x] Add `concurrency: 1` to `compute_betweenness` for symmetry with PageRank. It is already exact
      Brandes and already deterministic, so this costs nothing and proves nothing. Do not generalize
      the reasoning.
- [x] Keep `check_supplier_projection` and its UNDIRECTED comment block.
- [x] Leave the Story 2 path untouched, including `place_cutoff` itself, which `contagion_cutoff`
      still uses for THR-04. No Louvain, no new projection, no canonical relabeling.

### Rebuild exit criteria

- Generator runs clean and every build assert passes, including the degree constraint, the exposure
  constraint, and the three structural asserts.
- THR-03 resolves from the percentile, Cascade clears it, and the clearing cohort has more than one
  member.
- The three-legs check passes against the rebuilt graph.
- Two consecutive runs produce the same betweenness ranking.
- `guard.py` clean against live Unity Catalog and the live Genie space.
- **The Unity Catalog semantics read back from `information_schema` match what `upload.py`'s
  SEMANTICS dict meant to send.** This is not what `guard.py` checks. `check_unity_catalog` also
  reads `information_schema`, but it scans for governed vocabulary, so a comment that failed to
  apply at all reads as clean: absent text leaks nothing. Fidelity is the separate question, and it
  is the one that caught a change recorded as applied but missing from the deployed system twice in
  this project's history, once with the root cause never found. Compare the comment that came back,
  not the statement that was issued.
- Story 2 still holds: the Jade assert, THR-04 still between Jade and the next trading customer, and
  the three landmine asserts.

**When a Story 2 assert fails, ask whether a premise broke or an output moved.** The regenerate
re-rolls the filler groups Jade is ranked against. The landmine asserts are construction facts, so a
failure means fix the generator. `assert_pagerank` is not: it asserts Jade is top by weighted
PageRank, so "fix the generator" there can mean tuning filler stakes until Jade wins, which is
banned. The real test is whether some clean trading account other than Jade came to sit under
concentrated ownership of failure. Three relationships held on the green build and are what that test
reads against: fat stakes run only between two defaulted parties, a clean owner's stake over a
defaulted subsidiary stays small, and no controlling chain terminates at a clean trading account
other than Jade's. If one broke, the filler generator broke its own premise and fixing
it is the work. If none did and Jade still lost, weighted PageRank is not measuring what Story 2
claims on this network, which is a finding. Two honest iterations, then escalate. Suspect the
joint-stake block first.

**If the fix requires moving THR-04 to a cohort percentile, stop and escalate.** That is the THR-03
fix applied to Story 2 by analogy, and it looks principled. THR-04's one-winner shape survives only
because Story 2 is out of scope, so changing it is a redesign of Story 2, which `CONTRACT.md` section
8 bans. It needs that line reopened rather than worked around.

## Re-probe, after the rebuild

### The probe harness, and why it logs

Probes run against the MAS endpoint (Run B) through `probe_audited.py` in the session scratchpad. One
question per invocation, each in a fresh conversation:

    rtk proxy uv run probe_audited.py "the question" --label A1 --max-turns 30

It drives the MCP approval loop, auto-approving every Neo4j call, and writes an append-only JSONL
audit log at `<label>.jsonl` flushed after every API round trip. The flush is the point. The earlier
script printed only after the loop finished, so a run killed mid-loop wrote nothing, which is exactly
how one re-probe was lost. With the audit log a killed run still leaves everything up to its last
completed call on disk, untruncated, while stdout mirrors each turn as it happens. Deep traversals
run past the old cap of twelve turns, so raise `--max-turns` for any question that walks the full
commodity chain. The script is scratchpad tooling and is recreated per session rather than living in
the repo.

### Run A re-probed, six questions, and the ceiling held

Run against the re-synced space with `make guard` clean on every surface first. Each question in its
own fresh conversation, verbatim, no follow-ups and no priming turns.

- **No recursive CTE on any question, six for six.** Including both questions that use chain
  language. Moving Cascade two tiers back did not raise the ceiling, which was the largest open risk
  in the rebuild.
- **The sub-tier absorbs the dependency query, exactly as designed.** Asked what the glass bottle
  suppliers depend on, Run A wrote one hop and returned the container glass processors. Cascade does
  not appear in the result set.
- **Both cohort questions behaved.** Counting connections returns a background supplier, so leg 2
  holds live and not only in the assert. The raw glass subcategory returns a cohort of furnaces with
  Cascade among them rather than Cascade alone.
- **Beat 1 showed no spread this run.** Three fresh asks, all three on the same axis. Claim A held
  on all three, nothing cited a governed definition. Claim B did not appear, which is what the
  two-claim rule exists for and needs no change, since `DEMO.md` already says to narrate the
  ungroundedness when the asks agree.

### The convergence question flipped, and the contract moved rather than the data

The invited convergence question previously returned the protagonist as a single row. It now returns
no. Run A builds the same well-formed one-hop convergence query and correctly finds that no direct
upstream serves every Americas bottle maker, because the processor tier now sits in between. The
graph, traversing the commodity-scoped chain, returns yes and names the supplier. Two runs, one
question, opposite words.

**`CONTRACT.md` section 1 has been rewritten rather than the topology.** The owner's ruling is that a
Run A answer that is false at full depth is a legitimate finding and the strongest available
evidence for the graph, and that the earlier "Run A is never wrong" absolute overshot what it was
protecting against. Sections 1, 2 and 8 now carry the distinction that matters: an **emerged** wrong
answer is evidence, an **engineered** one is a plant, and the second is still banned outright. This
result qualifies because the topology that produced it was built to stop the protagonist being a cut
vertex, and the result was discovered by asking.

**On stage the narration is the mechanism, never the verdict.** Genie looks one level deep by
default and could likely be prompted deeper. That sentence is true, sufficient, and costs the demo
nothing, because default behaviour is what an analyst actually gets. Framing any beat as Genie being
wrong or beaten is now explicitly banned in section 8.

**Stability measured, five asks, and the flip held every time.** The SQL varied on every ask, a
boolean case, a zero-row filter, a full ranked list with a supplies-all flag, an overlap listing, and
the conclusion was identical five for five. Answer stable while the query is generative is the
strongest form this evidence could take, and it is still five asks on one build rather than a
guarantee. The beat carrying it must still work if Run A answers the other way, and the presenter
narrates the mechanism rather than the verdict per `CONTRACT.md` section 1.

- [x] Re-run the four probe questions plus a Beat 1 spread run against rebuilt data.
- [x] **Repeat the convergence question enough times to establish whether the flip is stable.** New,
      and it comes out of the ruling above rather than out of the original plan.
- [x] **Does Genie reach for recursion once Cascade sits two tiers back?** The one-hop ceiling is
      what the demo's structure relies on. The shape to test is that a one-hop query returns the
      sub-tier vendors and stops, so Cascade never enters the result set. If Genie writes a recursive
      CTE, the beats need restaging. The load-bearing claim survives either way, because a recursive
      answer still cites no governed definition.
- [x] Re-probe the exact phrase "common upstream supplier." If Genie adds a second hop by hand rather
      than recursing, the convergence caveat needs stating more carefully than "one join."
- [x] **Re-ask the convergence question the presenter invites, verbatim:** "do all our Americas glass
      bottle suppliers share a common upstream supplier?" This is the frozen phrasing for the question
      `CONTRACT.md` section 4 says to invite rather than hope nobody asks. Run A answered it correctly
      while Cascade sat one hop away, so what the re-probe establishes is whether that still holds
      with Cascade two tiers back.
- [x] **Ask the two cohort questions directly.** A connection count over `supply_relationships` does
      not name Cascade, and `WHERE subcategory = 'raw glass'` returns a cohort of furnaces rather
      than Cascade alone. The build asserts the first and the second falls out of the intermediate
      subcategories above, but both are cheap to ask and the second is the one the rebuild can break
      silently.
- [ ] Read and record the betweenness top-N.
- [ ] Write the five beats from what the transcripts say. No scripted Run A answer.
- [ ] Confirm the three legs land as three distinct visible outputs in Beat 3. No build can check
      that they read as three different things to a room. If two land as the same slide, restage.
- [ ] **Walk Story 1 end to end and confirm Cascade is named in the finding, in the exposure
      question, and in how the figure is presented.** Each of those is checked somewhere in
      isolation. Nothing checks that the same name carries across all three, and a story that
      discovers Cascade then reports a figure the room cannot attribute to it has broken between
      beats rather than inside one.
- [ ] **Carry the criticality side-by-side in Beat 3.** `CONTRACT.md` section 5 makes it scripted
      rather than optional: ask "what is our single biggest point of failure in our supply base?" of
      both runs. It is safe to ask precisely because no beat depends on Run A answering any
      particular way. Record both, script neither.

### The commodity-root re-probe: a wording that lands Cascade

A commodity-root re-probe was run against Run B, the MAS serving endpoint, to find a natural business
question that makes the graph name Cascade Glassworks (SUP-901) as the answer reliably, rather than
stopping at the container-glass processor tier above it. The reason this needed settling: an earlier
re-probe found that questions scoped to the Americas glass bottle suppliers, or to which Critical
Supplier is upstream, stop one hop up at the processors and name the processor Fairview Container
Works (SUP-907). Ranked by betweenness, Cascade is the lowest member of the Critical Supplier cohort,
so no "which is most critical" or "what converges" phrasing selects it. Something had to point the
question at Cascade without pointing it past Cascade.

The probe used the audited harness with the approval cap raised past the old limit. Three wordings,
several fresh runs each, one question per fresh conversation.

- Wording A, "Trace the raw glass supply for our Americas bottle production back to its source, which
  supplier is at the bottom of that chain," wandered into deep raw-material queries or listed Cascade
  among several furnaces. No clean run where Cascade was the single stated answer.
- Wording B, "Every container-glass processor that serves our Americas bottle makers buys its raw
  glass from somewhere. Is there a single upstream supplier they all depend on for it," named Cascade
  Glassworks every run as the single upstream source that all the Americas container-glass processors
  depend on for raw glass, and cited SUP-901 explicitly on some of those runs. Most of the runs
  reached the answer with shallow queries rather than deep variable-length traversals, so on stage it
  costs only a handful of live approvals.
- Wording C, "Which supplier is the ultimate source of the raw glass behind our Americas glass
  bottles," overshot below Cascade into the feedstock, naming a raw-material supplier once and a
  different furnace once. No clean hit.

The lesson, which the stalled agent's own note corroborated: any "source," "bottom," or "ultimate"
framing keeps pulling the stated answer below Cascade into the feedstock tier of cullet, silica sand
and soda ash. Scoping the question to the processors' shared upstream dependency lands on Cascade and
stops there. That is why wording B works and A and C do not.

The answers were graph traversals returning the structural sole-source relationship, not a figure
that could have come from a Delta table, so there is no leakage. One run stalled with an empty log
and was killed. The completed runs survived only because the audited harness flushes to disk per
turn, which is the reason that harness was built.

The decision this settles: wording B becomes Beat 3's question that lands on Cascade, and Cascade
stays the protagonist. Re-landing the beat on Fairview is not needed. This also closes the "Open for
the re-probe to settle" item in the chord-ratio build subsection above, which asked whether two glass
suppliers on the Americas chain weakens Story 1: the scoping question returns the single upstream, so
Beat 3's punchline is one name, Cascade, even though the cohort contains two glass suppliers on that
chain. The landing wording for Beat 3 is settled here; the checklist item to write the five beats
stays open, because that work is not done.

## Docs, last

- [x] **`DEMO.md`: the Story 1 beats are rewritten, verified 2026-07-19 by sweep.** Beat 2 is a live
      repeated ask, Beat 3 shows the legs definition-first, and Beat 4 is built around the five-unit
      comparison with the bottles causal argument. The two open TODO markers left in the beats are
      re-probe deliverables, the Beat 3 transcript and the Beat 4 wording, not doc-writing. For the
      record, what the rewrite had to cover: delete the honesty caveat about the number not being
      attributable to Cascade, which
      was true of the unscoped measure and is not true of this one. Delete every "expected Run A
      answer" and do not reintroduce it in another form. Remove quoted counts and scores. It quotes
      the old TERM-05 "narrowest bridge" phrasing twice, including once as the finding Beat 3 lands
      on, and both go. Carry the honest caveat that convergence is cheap in SQL once you know what to
      converge on, and add the note about inviting the convergence question rather than hoping nobody
      asks it. `CONTRACT.md` section 6 carries the verbatim phrasing.
- [x] **`DEMO.md`: the one-winner claims are deleted, verified 2026-07-19 by sweep.** For the record, two passages
      state the strict-max shape that `CONTRACT.md` section 7 replaces with cohort membership. Beat
      3's "The result" bullet says Cascade's precomputed betweenness is the strict maximum in the
      supplier network and that applying the governed cutoff confirms it is the only Critical
      Supplier. The Graph mechanics "The cutoff" bullet says the Supply Concentration Threshold is
      set from the score distribution so only Cascade clears it. The replacement for both is cohort
      membership: Cascade clears THR-03, and the clearing cohort has more than one member. The
      cutoff bullet is the more dangerous of the two, because "set so only Cascade clears it" is not
      merely stale wording, it describes the post-hoc threshold banned in `CONTRACT.md` section 8,
      so it must not survive in any reworded form. THR-03 is a hand-set percentile fixed before the
      run, and the rewrite says so.
- [ ] **The Story 1 diagram.** Redraw to show the independent glassworks feeding the protected units,
      because that contrast is now the Beat 4 argument, and to show Cascade one tier back from the
      bottle makers.
- [x] `README.md` and `DATA_ARCHITECTURE.md`, done 2026-07-19. The threshold semantics, exposure
      wording, and multi-cluster topology prose were already in rebuilt form, confirmed by sweep. The
      one change made was the table-fairness fix: both files now say `compliance_findings` and
      `owned_by` are in the space, with the two gold tables still kept out.
- [ ] **The Genie space,** which is hand-synced and not in this repo. The rebuild changes values
      rather than schema: no column is added or dropped, what moves is the set of subcategory values
      and the supply rows. So this is a filter-value re-sync rather than a schema migration, which
      makes it smaller than it reads and lets it be scheduled on its own. **It is larger than that
      sentence predicted, though, and the reason is worth knowing before the re-sync starts.** The
      rebuild adds four subcategory values rather than adjusting existing ones, and `guard.py` reads
      `COMMODITY_SUBCATEGORIES` through its `commodity_subcategories` helper, so all six glass
      subcategories are now scanned vocabulary. A space instruction or column comment that enumerates
      two of them starts failing the guard. That is the intended behavior rather than a regression,
      but it means the re-sync can fail the guard on text that passed before and was never touched.
      Re-sync the region and
      subcategory filters, re-verify no example SQL primes Cascade, and
      re-read the subcategory column comment and the `supply_relationships` SEMANTICS entry to
      confirm they stay neutral. **Add `compliance_findings` and `owned_by` to the space,** which
      `CONTRACT.md` section 3 requires both engines to have and which the docs now assume are in.
      Adding `compliance_findings` restores the fanout it was formerly kept out to prevent, so the
      space instructions must gain the rule to aggregate each one-to-many branch to grain or read the
      `customer_risk_exposure` metric view, and the "the metric view is the only place finding counts
      are available" wording must go. Verify against the live workspace, not against a worklog: twice
      here a change recorded as applied was absent from the deployed system.
- [ ] **The transcript PDFs.** The v1 and v2 sets are already moved to `worklog/archive/transcripts/`;
      what remains open is exporting the v3 set. Every
      transcript from both stories is stale after the regenerate by definition, so the v3 set
      captured in the re-probe replaces them and is not compared against v2. Stamp each new
      transcript with the seed and the as-of date, both read from the top level of
      `data/ground_truth.json`, so which build a transcript came from is never a question again.

## THR-03 rounding, after the re-probe

`concentration_cutoff` in `gds.py` resolves the nearest-rank percentile, rounds the result to two
decimals, and then selects the cohort with `>=` against that rounded value. The scores it selects
against carry four. When the rounding goes up, the supplier whose score defined the percentile no
longer clears the cutoff derived from it. When it goes down, suppliers scoring below the percentile
join the cohort. Neither is visible in the output: both produce a plausible cutoff and a plausible
cohort, and the build prints only the rounded figure.

This is reachable because Cascade sits on the boundary. It ranked last in the clearing cohort on the
builds recorded above, which is exactly the position the defect acts on, so a regenerate has roughly
even odds of `assert_betweenness` failing on arithmetic rather than on topology. That failure prints
the CONTRACT section 7 message about fixing the topology and spending an iteration, which is the
wrong diagnosis and the expensive one. The pre-flight section below makes a demo-day regenerate a
documented event, so this is reachable from the room and not only from the build loop.

**It is deliberately not fixed before the re-probe.** Fixing it can move THR-03's resolved value and
can move cohort membership, and the re-probe is the step that captures what the graph actually
returns when asked. A transcript captured against one cutoff with a fix applied after it leaves no
way to tell which cutoff the transcript describes.

- [ ] **Record the raw numbers during the re-probe,** at full precision rather than as displayed:
      Cascade's betweenness, the unrounded nearest-rank score `concentration_cutoff` selected, the
      rounded value written to the graph, and every cohort member's score. The build log carries the
      rounded figures only, so this has to be read off the scores rather than off the log.
- [ ] **Establish which way the rounding went on the probed build,** and whether Cascade is the
      supplier that defined the percentile. If it is and the rounding went down, the transcripts
      describe a cohort the fix would not change and the fix lands cleanly. If it went up, the
      probed build already dropped a supplier from its own cohort, and the cohort questions in the
      re-probe need re-reading before their answers are trusted.
- [ ] **Then fix it:** select the cohort against the unrounded percentile score, and round only for
      the value written to the Threshold node, to `thresholds.csv`, and to the display. Re-run and
      confirm the cohort is unchanged, or that the re-probe findings still hold if it moved.

**Do not fold this into the topology stopping rule.** It is an arithmetic defect in the cutoff
resolver rather than an honest attempt at the agreed topology, so a build failing
`assert_betweenness` for this reason has not spent an iteration. Keeping that distinction visible is
why this is written down rather than fixed quietly.

## Pre-flight, on the day

These are not rebuild items and they do not close when the rebuild does. Both guard against drift
between the build and the room, so a build-time pass says nothing about either. They run last, after
everything else has passed, and they run on every demo day rather than once.

- [ ] **The vocabulary guard, standalone against the live Genie space,** via `make guard`. The space
      is hand-synced and can change after a build. This protects the load-bearing claim, which is why
      it is the check that runs last rather than only first.
- [ ] **Today's quarter still matches the quarter the build was shaped around,** read from the "Last
      full quarter" row that `expected_results.py` renders out of the `story1_hidden_glassworks`
      block. `AS_OF` is the build date, so a calendar quarter rolling between the build and the demo
      silently changes what "the most recent full quarter" means in Beat 4. The build-time quarter
      assert cannot catch this. The fix when it fails is a regenerate, which is one `make demo`.

Keep this section when the rest of the file is deleted. It moves to `DEMO.md` rather than going away.
