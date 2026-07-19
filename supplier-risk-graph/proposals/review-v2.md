# Review v2: rebuild readiness

A findings review of the Story 1 rebuild against `proposals/REBUILD.md` and `proposals/CONTRACT.md`.

**State in one line.** The code rebuild is done and verified: the generator and GDS changes match every
claim in REBUILD.md, and the DEMO, README, and DATA_ARCHITECTURE prose is already rewritten to the
post-rebuild topology and framing. What remains is one deferred arithmetic defect, the re-probe
write-up, a live Genie-space re-sync, the Story 1 diagram, and a small number of doc reconciliations.

**Already verified complete, so not listed below.** The generator structural asserts, the depth leg,
all the deletions REBUILD.md called for, the four-cluster topology with distinct non-glass bridges,
the feedstock fan-in, the processor tier, the `check_exposure` recompute, the GDS cohort resolution,
`assert_betweenness` as a cohort check, `report_degree_overlap` as print-not-assert, and the
Story 2 path left untouched. DEMO.md carries no scripted Genie answers, no quoted figures, no
em-dashes, correct engine naming, and beats and frozen questions that match the contract.

The findings are ordered by severity: blocking first, then open re-probe work, then documentation,
then reconciliations and pre-flight.

---

## 1. **THR-03 rounding defect in `concentration_cutoff`**

`concentration_cutoff` in `gds.py` resolves the nearest-rank percentile, rounds that cutoff to two
decimals, and then selects the clearing cohort with a `>=` comparison against scores that carry four
decimals. Cascade sits on the cohort boundary, last in the clearing cohort on the recorded builds,
which is exactly the position the mismatch acts on. So a regenerate can push the rounded cutoff above
Cascade's own unrounded score and make `assert_betweenness` fail on arithmetic rather than on
topology. That failure prints the CONTRACT section 7 message telling the operator to fix the topology
and spend an iteration, which is the wrong diagnosis and the expensive one. It is reachable from a
demo-day regenerate, not only from the build loop.

### ELI5

A ride has a height limit. You measure the limit line to the nearest centimeter, but you measure each
child to the nearest millimeter. A child standing exactly on the line can be let on or turned away
depending only on that rounding, even though the child has not changed. Cascade is the child on the
line, so a tiny rounding wobble can wrongly turn it away and make the build shout "the ride is broken"
when only the ruler was sloppy.

### Recommended fix

Do the two prerequisite steps first so existing transcripts stay interpretable: record the raw numbers
on the currently probed build (Cascade's betweenness, the unrounded nearest-rank score, the rounded
value, and every cohort member's score), and establish which way the rounding went. Then select the
cohort against the unrounded percentile score and round only for the value written to the Threshold
node, to `thresholds.csv`, and to the display. Re-run and confirm the cohort is unchanged, or that the
re-probe findings still hold if it moved. Per REBUILD.md, a build failing `assert_betweenness` for this
reason has not spent a topology iteration, so keep that distinction visible when it fires.

---

## 2. **Dirty working tree before a destructive rebuild**

Four tracked files are uncommitted: `DEMO.md`, `README.md`, `DATA_ARCHITECTURE.md`, and
`data/thresholds.csv`. REBUILD.md's rebuild precondition and `worklog/lessons-learned.md` both require a
clean tree before `make demo`, because a regenerate on a dirty tree has destroyed uncommitted work
before, and `thresholds.csv` is load-bearing for the build.

### ELI5

Before you tear the kitchen apart to rebuild it, you take your loose valuables off the counter. Right
now there are loose edits sitting on the counter, and `make demo` is a wrecking crew that does not
check the counter first.

### Recommended fix

Commit or revert the in-progress doc edits, and confirm the `thresholds.csv` state, before running
`make demo`.

---

## 3. **DATA_ARCHITECTURE.md contradicts the code on the `classifications` table**

The `classifications` gold-table row in `DATA_ARCHITECTURE.md` still states the table holds "never
Critical Supplier or Ownership Risk." That is no longer true. `write_critical_supplier_labels` in
`gds.py` now materializes Critical Supplier `CLASSIFIED_AS` edges, `upload.py` includes those rows in
the `classifications` gold table, and the updated README already says Critical Supplier carries these
edges. The doc now contradicts both the code and the README.

### ELI5

One instruction sheet says "this box never contains apples." Someone started putting apples in the box
and updated a different sheet to say so, but this sheet still says no apples. A reader who trusts the
old sheet is misled.

### Recommended fix

Update the `classifications` row to match the code: Critical Supplier now carries edges, written by
`gds.py` from the governed threshold as a stand-in for a production batch job, and Ownership Risk alone
is resolved live and carries none.

---

## 4. **Decision needed: does the Critical Supplier write-back fit CONTRACT section 8**

Section 8 bans syncing GDS scores or graph classifications into gold tables. Critical Supplier is a
graph-native classification that now lands in the `classifications` gold table. It is kept safe only
because `banned_tables` in `guard.py` holds that table out of the Genie space, so the lakehouse-only
engine cannot read it. This change is not recorded in REBUILD.md, so whether it is an accepted
refinement or a section 8 violation is a judgment the owner has to make, not one to settle silently.

### ELI5

There is a rule: do not write the secret answer in the shared notebook. Someone wrote the answer in a
notebook but locked that notebook in a drawer nobody can open. Is that allowed? It depends on whether
the rule was about writing it down at all, or about someone being able to read it.

### Recommended fix

Owner ruling required. Either accept it and add a one-line clarification to section 8 that the ban
targets space-visible gold tables, or back the write-back out. Either way, verify at pre-flight that
`banned_tables` keeps `classifications` out of the live space, read back from the live space rather than
from a worklog.

---

## 5. **The five beats are not yet written from transcripts**

The re-probe deliverables are open. The betweenness top-N is not recorded, the check that the three
legs land as three distinct visible outputs is not confirmed, the walk that carries the Cascade name
across the finding, the exposure, and the presentation is not done, and the criticality side-by-side is
not recorded. DEMO.md carries two live TODO markers, one for the Beat 3 Genie + Graph transcript and
one for the Beat 4 exact wording.

### ELI5

The stage play has its scenery built and its rules written, but the lines for two scenes are still
marked "fill this in after we watch the rehearsal." You cannot perform until you have watched the
rehearsal and written those lines.

### Recommended fix

Run the re-probe deliverables, capture the Genie + Graph transcript for Beat 3, confirm the three steps
read as three distinct outputs on screen, pin the Beat 4 wording verbatim, and record the numbers at
full precision, which also feeds the THR-03 fix in finding 1. Write the beats from what the transcripts
say, never from a predicted answer.

---

## 6. **No Story 1 topology diagram exists**

Only the architecture and classification-provenance diagrams are present in the repo. REBUILD.md asks
for a Story 1 diagram showing the independent glassworks feeding the protected units and Cascade one
tier back from the bottle makers. Beat 4's contrast argument now rests on that picture.

### ELI5

The tour guide wants to point at a map showing the one road every truck secretly shares, but there is
no such map drawn yet, only the building floor plan.

### Recommended fix

Create the Story 1 topology diagram: the regional clusters, the processor tier, Cascade as a narrow
waist two tiers back, and the independent glassworks feeding the other business units.

---

## 7. **Live Genie space re-sync not verified**

The Genie space is hand-synced and lives outside the repo. The rebuild adds four subcategory values, so
all six glass subcategories are now guard-scanned vocabulary. A space instruction or a column comment
that enumerates two of them can newly fail the guard even though it passed before and was never
touched. That is intended behavior, not a regression, but it means the re-sync can fail the guard on
text that used to be clean.

### ELI5

The rulebook the referee reads from is kept in a separate building, and nobody has checked that the
separate copy matches the new rules. The new rules also made more words forbidden, so old sentences
that used to be fine might now break a rule.

### Recommended fix

Re-sync the region and subcategory filters against the live workspace, re-verify no example SQL primes
Cascade, re-read the subcategory column comment and the `supply_relationships` SEMANTICS entry to
confirm they stay neutral, then run `make guard` live. Verify by reading state back from the live space.

---

## 8. **Unity Catalog semantics fidelity is not tooled**

The exit criterion wants the deployed Unity Catalog comments to match what `upload.py`'s SEMANTICS dict
meant to send. `guard.py` only scans for vocabulary leaks, so a comment that silently failed to apply
reads as clean, because absent text leaks nothing. A change recorded as applied but missing from the
live system has happened twice in this project's history, once with the root cause never found.

### ELI5

The spell-checker only yells if you write a bad word. It never notices if a whole sentence you meant to
write simply did not show up. So a missing sentence passes the check even though it is missing.

### Recommended fix

After upload, compare the comment that came back from `information_schema` against the SEMANTICS text
that was meant to be sent, as a separate read-back. This is a different question from the leak scan and
`guard.py` does not answer it.

---

## 9. **v3 transcript PDFs not produced**

The v1 and v2 transcript sets are correctly archived in `worklog/archive/transcripts/`, but no v3 set
exists yet. The v3 set captured in the re-probe is meant to replace them.

### ELI5

You filed away the old rehearsal recordings, but you have not yet saved the recording of the new
rehearsal that everything now depends on.

### Recommended fix

Export the v3 re-probe transcripts, stamp each with the seed and the as-of date read from
`ground_truth.json`, and place them in `worklog/archive/transcripts/`, replacing rather than diffing
against v2.

---

## 10. **DEMO.md mislabels the convergence-caveat question as frozen**

In "The convergence caveat, said out loud," DEMO.md calls the bottle-maker-scoped question the frozen
phrasing, but that question is not in CONTRACT section 6. Section 6 freezes only the processor-scoped
Beat 3 convergence question and the two others. DEMO.md labels as authoritative a phrasing the stated
authority does not carry.

### ELI5

A sign says "official wording, see the rulebook," but that exact wording is not actually in the
rulebook. It is a real and useful sentence, it is just not filed where the sign claims.

### Recommended fix

Either add this invited-caveat question to CONTRACT section 6, since it is the one section 4 tells the
presenter to invite, or soften DEMO.md's wording from "the frozen phrasing" to "the invited phrasing."

---

## 11. **REBUILD.md "Docs, last" checkboxes are stale**

The checkboxes under "Docs, last" are unchecked, but the DEMO, README, and DATA_ARCHITECTURE prose
rewrite is done. Only three documentation items remain genuinely open: the Story 1 diagram (finding 6),
the live Genie re-sync (finding 7), and the Unity Catalog fidelity read-back (finding 8). The stale
boxes misrepresent the state of the work.

### ELI5

The chore chart still shows the dishes as not done, but the dishes are actually done. Someone forgot to
tick the box. A couple of chores really are still open, so do not tick everything at once.

### Recommended fix

Reconcile the checkboxes against the actual doc contents, keeping the project rule that "done" must name
the check that proves it. The re-sync and the read-back stay open until verified against the live
system.

---

## 12. **Demo-day quarter alignment**

The build is dated to its generation day, and Beat 4 derives "the most recent full quarter" from that
date. Today the current quarter and the build's quarter still agree, but a calendar quarter rolling
between the build and the demo silently changes what Beat 4 means, and the build-time quarter assert
cannot catch it. No Makefile target automates this check.

### ELI5

A report says "last month's numbers." If you read it in a new month, "last month" quietly means a
different month than the one the numbers actually describe, and nothing on the page warns you.

### Recommended fix

On demo day, re-run `make expected` and confirm the "Last full quarter" row still matches the current
quarter, and run `make guard` live. If the quarter has rolled, the fix is a regenerate, which is one
`make demo`. Keep this in the pre-flight section.

---

## 13. **`MAX_PROBE_TIERS` survives in a comment**

The constant and its backtracking logic are deleted, but the token `MAX_PROBE_TIERS` still appears once
in an explanatory comment in the generator. Functionally deleted, not textually absent.

### ELI5

You threw out the old tool, but there is still a sticky note on the wall mentioning it. Harmless, just
slightly confusing to the next person.

### Recommended fix

Optional cleanup. Leave the comment if it earns its keep as history, or trim the reference.

---

## 14. **REBUILD.md self-teardown pending**

REBUILD.md instructs that the file be deleted when the rebuild is done, after moving its pre-flight
section into DEMO.md. That has not happened, which is correct because the rebuild is not finished, but
it is worth tracking so it is not forgotten at the end.

### ELI5

The instruction note says "throw me away when the job is done." The job is not done, so keep it, just
remember the note asked to be thrown away later.

### Recommended fix

When the remaining findings close, move the pre-flight section into DEMO.md and delete REBUILD.md, per
its own instruction.
