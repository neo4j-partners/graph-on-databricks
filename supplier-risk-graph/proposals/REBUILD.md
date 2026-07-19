# Rebuild work list

The topology rebuild and everything downstream of it. Delete this file when it is done, after moving
the pre-flight section to `DEMO.md`, since those two checks run on every demo day and not once.

`proposals/CONTRACT.md` still holds the standing rules. This file holds only what is left to do.

## Status

Guards are landed and green and the routing gate is cleared, so nothing in this section is open.
`guard.py`, the three-legs check, the quarter assert, the Story 2 landmine asserts, and now the three
structural asserts.

- [x] **The three structural asserts. Landed, and they were missing rather than green.** An earlier
      version of this line recorded them as landed alongside the other four. They were not in the
      code: no forest check, no intermediate-share check, no depth check, and no
      `MIN_INTERMEDIATE_FRACTION` for the stopping rule to govern, which is the failure mode
      `CONTRACT.md` section 7 exists to catch. They are now `check_supply_structure` in
      `generate_data.py`, called from `main` ahead of `check_story1`, with
      `MIN_INTERMEDIATE_FRACTION` and `MIN_SUPPLY_TIERS` sitting with the other
      governed constants. All three pass against the pre-rebuild build, each by a wide margin, and
      the realized figures print to the build log every run rather than being asserted.
- **Green here does not mean the topology is healthy, and the margins are the reason to say so.** All
  three clear comfortably on the build whose betweenness is trivially maximal because Cascade is a cut
  vertex. They catch star-forest collapse and nothing else, so the rebuild has to keep clearing them
  while fixing what they cannot see. The depth floor has so much headroom on the background network
  that it will not bind during the rebuild, and the intermediate share is far enough above its floor
  that a failure there would signal something badly wrong rather than a near miss.
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

- [ ] **Several regional clusters with multiple inter-cluster bridges,** not two clusters joined by
      one. Cascade is currently a literal cut vertex, which makes its betweenness trivially maximal
      and invites the fair question of why a global supply network has a single bridge.
- [ ] **The extra bridges carry something other than glass.** More bridges make betweenness
      interesting and also give the exposure measure more places to leak. Commodity scoping is what
      keeps those compatible.
- [ ] **The glass chain is a chain of glass companies.** Every sub-tier vendor between Cascade and
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
- [ ] **Real intermediate subcategories for the sub-tier,** not raw glass doing double duty as both
      Cascade's peers and its customers. Double duty breaks the cohort check, since `WHERE
      subcategory = 'raw glass'` is supposed to return other furnaces. The processor tier sits
      downstream of the furnace, so name it for what it makes, `container glass` being the obvious
      one. Cullet is not a candidate here: the agreed topology puts it upstream as feedstock, which
      is where it belongs physically and where it does the fan-in work.
- [ ] **The feedstock tier is glass too, and it is easy to forget.** Cascade's feedstock vendors are
      what give it the fan-in the score depends on, so if they are not in `COMMODITY_SUBCATEGORIES`
      the paths through Cascade stop being commodity-carrying at exactly the point the story turns
      on. Cullet, sand and soda ash all belong in the `glass` entry alongside the processor tier.
- [ ] **Keep the glass chain shallow.** Cascade to sub-tier to tier-1 to business unit, so Beat 3's
      convergence paths stay legible on screen. The four-tier assert is cleared by the background
      network, which is also what gives betweenness a real distribution.

**The premise and the banned bar, distinguished.** Constructing the sole-source premise means the
generator decides which glass suppliers the Americas draws from, and that code will look like the bar
being deleted below. The test: if an edit fixes a count, a score, or a predicted answer, it is the
bar wearing new clothes. If it fixes which structural relationship is true, it is the premise, and
building the premise is the work.

### Generator, delete

- [ ] `SUP_HUB_DEGREE_MARGIN` and the decoy-hub boost loop. Leave SUP-109 as an ordinary supplier
      rather than removing the row, so downstream RNG draws do not shift for no benefit.
- [ ] `CASCADE_A_LINKS` and `CASCADE_B_LINKS` as hand-tuned counts.
- [ ] The `americas_glass == set(TIER1_IDS)` assert and the glass-bottle bar in `make_supplies`.
- [ ] The "raw glass is reserved for Cascade" reservation, so the subcategory holds a cohort.
- [ ] The rank-disagreement asserts, the `pairs_separated` strict-max assert, and the cut-vertex
      assert, which the connected-component check replaces.
- [ ] **Both currency bands in `check_exposure`.** The BU-03 band is pure surplus, because the
      recompute above it already confirms the figure sums the right unit, quarter, and column. The
      Jade band has no recompute anywhere, so it is a replacement rather than a deletion: recompute
      Jade's exposure from the source rows, assert the caller's figure against it, then drop the
      band. A fitted band gets replaced by a recomputation, not removed.

**The RNG stream will shift and there is no way around it.** Adding `raw glass` to the name-pool dict
adds an `rng.shuffle`, and adding it to `SUBCATEGORIES["packaging"]` changes an `rng.choice` from four
options to five. `make_suppliers` runs early off the shared `rng`, so the blast radius is every figure
in `ground_truth.json`, including Story 2. That is expected and fine. What must survive is the
structural asserts, and re-verifying them is part of this step.

### GDS

- [ ] **Rework the THR-03 computation** to resolve the generator's `SUPPLY_CONCENTRATION_PERCENTILE`
      rather than compute a one-winner cutoff. `place_cutoff` and `concentration_cutoff` for Story 1
      go. This closes the current disagreement where the graph states a governed percentile in
      THR-03's `basis` and computes its cutoff by another route.
- [ ] **Delete the strict-max requirement in `assert_betweenness`.** Replace with the cohort check,
      that Cascade clears THR-03. Report the ranking, do not assert who wins.
- [ ] Add `concurrency: 1` to `compute_betweenness` for symmetry with PageRank. It is already exact
      Brandes and already deterministic, so this costs nothing and proves nothing. Do not generalize
      the reasoning.
- [ ] Keep `check_supplier_projection` and its UNDIRECTED comment block.
- [ ] Leave the Story 2 path untouched, including `place_cutoff` itself, which `contagion_cutoff`
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

- [ ] Re-run the four probe questions plus a Beat 1 spread run against rebuilt data.
- [ ] **Does Genie reach for recursion once Cascade sits two tiers back?** The one-hop ceiling is
      what the demo's structure relies on. The shape to test is that a one-hop query returns the
      sub-tier vendors and stops, so Cascade never enters the result set. If Genie writes a recursive
      CTE, the beats need restaging. The load-bearing claim survives either way, because a recursive
      answer still cites no governed definition.
- [ ] Re-probe the exact phrase "common upstream supplier." If Genie adds a second hop by hand rather
      than recursing, the convergence caveat needs stating more carefully than "one join."
- [ ] **Re-ask the convergence question the presenter invites, verbatim:** "do all our Americas glass
      bottle suppliers share a common upstream supplier?" This is the frozen phrasing for the question
      `CONTRACT.md` section 4 says to invite rather than hope nobody asks. Run A answered it correctly
      while Cascade sat one hop away, so what the re-probe establishes is whether that still holds
      with Cascade two tiers back.
- [ ] **Ask the two cohort questions directly.** A connection count over `supply_relationships` does
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

## Docs, last

- [ ] `DEMO.md`: rewrite the Story 1 beats. Beat 2 becomes a live repeated ask. Beat 3 shows the legs
      definition-first. Rewrite Beat 4 around the five-unit comparison and add the bottles causal
      argument. Delete the honesty caveat about the number not being attributable to Cascade, which
      was true of the unscoped measure and is not true of this one. Delete every "expected Run A
      answer" and do not reintroduce it in another form. Remove quoted counts and scores. It quotes
      the old TERM-05 "narrowest bridge" phrasing twice, including once as the finding Beat 3 lands
      on, and both go. Carry the honest caveat that convergence is cheap in SQL once you know what to
      converge on, and add the note about inviting the convergence question rather than hoping nobody
      asks it. `CONTRACT.md` section 6 carries the verbatim phrasing.
- [ ] **`DEMO.md`: delete the one-winner claims, which the item above does not cover.** Two passages
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
- [ ] `README.md` and `DATA_ARCHITECTURE.md`: threshold semantics and the new exposure wording. Both
      describe the two-cluster-bridge topology in prose in several places and go stale under the
      rebuild.
- [ ] **The Genie space,** which is hand-synced and not in this repo. The rebuild changes values
      rather than schema: no column is added or dropped, what moves is the set of subcategory values
      and the supply rows. So this is a filter-value re-sync rather than a schema migration, which
      makes it smaller than it reads and lets it be scheduled on its own. Re-sync the region and
      subcategory filters, re-verify no example SQL primes Cascade, and
      re-read the subcategory column comment and the `supply_relationships` SEMANTICS entry to
      confirm they stay neutral. Verify against the live workspace, not against a worklog: twice here
      a change recorded as applied was absent from the deployed system.
- [ ] **The transcript PDFs.** Move the v1 and v2 sets to `worklog/archive/transcripts/`. Every
      transcript from both stories is stale after the regenerate by definition, so the v3 set
      captured in the re-probe replaces them and is not compared against v2. Stamp each new
      transcript with the seed and the as-of date, both read from the top level of
      `data/ground_truth.json`, so which build a transcript came from is never a question again.

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
