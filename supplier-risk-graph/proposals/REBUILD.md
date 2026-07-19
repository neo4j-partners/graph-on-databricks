# Rebuild work list

The topology rebuild and everything downstream of it. Delete this file when it is done, after moving
the pre-flight section to `DEMO.md`, since those two checks run on every demo day and not once.

`proposals/CONTRACT.md` still holds the standing rules. This file holds only what is left to do.

## Status

Guards are landed and green: `guard.py`, the structural asserts, the three-legs check, the quarter
assert, the Story 2 landmine asserts. One guards item is still open, below.

- [ ] **Run B routing probe.** Ask the Beat 1 and Beat 3 questions through Genie One against the
      current build and record whether the routing actually reaches the graph rather than falling
      through to the lakehouse. Routing is a property of the MCP wiring, not the data, so the answer
      survives the rebuild. A routing defect is the one Run B result that stops the demo, which is
      why it runs before the rebuild is paid for and not after.
- [ ] **TERM-05 alignment.** It says paths carry a commodity "into the business" while RULE-05 says
      "into a business unit". Per-unit matches MEAS-01 and is correct. One word, lands before the
      rebuild starts, because the wording is an input to the topology.

## The rebuild

One regenerate cycle, run repeatedly until clean. The generator changes, the GDS changes, `make
demo`, `make expected`. Do not try to split it into stages.

**Precondition: a clean tree.** The guards and the TERM-05 alignment land as commits before the first
regenerate runs. `worklog/lessons-learned.md` records a regenerate on a dirty tree destroying
uncommitted data, and this is one long regenerate loop, so the rule is stated here rather than
remembered.

**The stopping rule governs this whole section.** `CONTRACT.md` section 7 holds it: two honest
topology iterations, the percentile does not move, and `MIN_INTERMEDIATE_FRACTION` is a tripwire
rather than a dial. It is repeated as a pointer because the loop below is exactly where it gets
violated. If Cascade fails to clear THR-03 twice, check whether the sole-source assert passes and
escalate. Do not take a third run at the topology.

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
      commodity-carrying and the sole-source premise fails silently.
- [ ] **Real intermediate subcategories for the sub-tier,** not raw glass doing double duty as both
      Cascade's peers and its customers. Double duty breaks the cohort check, since `WHERE
      subcategory = 'raw glass'` is supposed to return other furnaces.
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
- Story 2 still holds: the Jade assert, THR-04 still between Jade and the next trading customer, and
  the three landmine asserts.

**When a Story 2 assert fails, ask whether a premise broke or an output moved.** The regenerate
re-rolls the filler groups Jade is ranked against. The landmine asserts are construction facts, so a
failure means fix the generator. `assert_pagerank` is not: it asserts Jade is top by weighted
PageRank, so "fix the generator" there can mean tuning filler stakes until Jade wins, which is
banned. The real test is whether some clean trading account other than Jade came to sit under
concentrated ownership of failure. If one did, the filler generator broke its own premise and fixing
it is the work. If none did and Jade still lost, weighted PageRank is not measuring what Story 2
claims on this network, which is a finding. Two honest iterations, then escalate. Suspect the
joint-stake block first.

## Re-probe, after the rebuild

- [ ] Re-run the four probe questions plus a Beat 1 spread run against rebuilt data.
- [ ] **Does Genie reach for recursion once Cascade sits two tiers back?** The one-hop ceiling is
      what the demo's structure relies on. The shape to test is that a one-hop query returns the
      sub-tier vendors and stops, so Cascade never enters the result set. If Genie writes a recursive
      CTE, the beats need restaging. The load-bearing claim survives either way, because a recursive
      answer still cites no governed definition.
- [ ] Re-probe the exact phrase "common upstream supplier." If Genie adds a second hop by hand rather
      than recursing, the convergence caveat needs stating more carefully than "one join."
- [ ] **Ask the two cohort questions directly.** A connection count over `supply_relationships` does
      not name Cascade, and `WHERE subcategory = 'raw glass'` returns a cohort of furnaces rather
      than Cascade alone. The build asserts the first and the second falls out of the intermediate
      subcategories above, but both are cheap to ask and the second is the one the rebuild can break
      silently.
- [ ] Read and record the betweenness top-N.
- [ ] Write the five beats from what the transcripts say. No scripted Run A answer.
- [ ] Confirm the three legs land as three distinct visible outputs in Beat 3. No build can check
      that they read as three different things to a room. If two land as the same slide, restage.

## Docs, last

- [ ] `DEMO.md`: rewrite the Story 1 beats. Beat 2 becomes a live repeated ask. Beat 3 shows the legs
      definition-first. Rewrite Beat 4 around the five-unit comparison and add the bottles causal
      argument. Delete the honesty caveat about the number not being attributable to Cascade, which
      was true of the unscoped measure and is not true of this one. Delete every "expected Run A
      answer" and do not reintroduce it in another form. Remove quoted counts and scores. It quotes
      the old TERM-05 "narrowest bridge" phrasing twice, including once as the finding Beat 3 lands
      on, and both go. Carry the honest caveat that convergence is cheap in SQL once you know what to
      converge on, and add the note about inviting the convergence question rather than hoping nobody
      asks it. `CONTRACT.md` section 4 carries the verbatim phrasing.
- [ ] **The Story 1 diagram.** Redraw to show the independent glassworks feeding the protected units,
      because that contrast is now the Beat 4 argument, and to show Cascade one tier back from the
      bottle makers.
- [ ] `README.md` and `DATA_ARCHITECTURE.md`: threshold semantics and the new exposure wording. Both
      describe the two-cluster-bridge topology in prose in several places and go stale under the
      rebuild.
- [ ] **The Genie space,** which is hand-synced and not in this repo. Re-sync the region and
      subcategory filters after the schema changes, re-verify no example SQL primes Cascade, and
      re-read the subcategory column comment and the `supply_relationships` SEMANTICS entry to
      confirm they stay neutral. Verify against the live workspace, not against a worklog: twice here
      a change recorded as applied was absent from the deployed system.
- [ ] **The transcript PDFs.** Move the v1 and v2 sets to `worklog/archive/transcripts/`. Every
      transcript from both stories is stale after the regenerate by definition, so the v3 set
      captured in the re-probe replaces them and is not compared against v2. Stamp each new
      transcript with its build identity, meaning seed, as-of date, and git sha, so which build a
      transcript came from is never a question again.

## Pre-flight, on the day

These are not rebuild items and they do not close when the rebuild does. Both guard against drift
between the build and the room, so a build-time pass says nothing about either. They run last, after
everything else has passed, and they run on every demo day rather than once.

- [ ] **The vocabulary guard, standalone against the live Genie space,** via `make guard`. The space
      is hand-synced and can change after a build. This protects the load-bearing claim, which is why
      it is the check that runs last rather than only first.
- [ ] **Today's quarter still matches the quarter in the build identity.** `AS_OF` is the build date,
      so a calendar quarter rolling between the build and the demo silently changes what "the most
      recent full quarter" means in Beat 4. The build-time quarter assert cannot catch this. The fix
      when it fails is a regenerate, which is one `make demo`.

Keep this section when the rest of the file is deleted. It moves to `DEMO.md` rather than going away.
