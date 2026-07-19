# supplier-risk-graph — CLAUDE.md

## Read this before proposing anything about the demo

`worklog/CONTRACT.md` is the authority for Story 1. Read it before suggesting a change to the
demo's narrative, questions, beats, data topology, or knowledge layer. `worklog/simplified-plan.md`
is the working detail behind it. Where they disagree, the contract wins.

## The core point, which is misread constantly

The demo is **ungrounded versus grounded**. It is NOT wrong versus right.

Genie Agent is a frontier LLM over tables. Ask it a business question and it returns a plausible
answer grounded in nothing but column names. The axis it picks is generative and not reproducible.
Genie One with the graph ontology returns an answer grounded in an authored definition, so it is the
same answer every time and a risk committee can act on it.

Run A is never wrong and is never beaten. Its answers are plausible, defensible, and anchored to
nothing.

## The rule that this project keeps violating

**Do not predict what Genie will answer, and do not engineer data so a predicted answer is wrong.**

Genie Agent is stochastic. Every previous version of this demo tried to pin down its answer and
build the story on top of that prediction. Each one got relitigated when the prediction turned out
to be untested or wrong. That is the single largest source of wasted work in this project's history.

Two claims, different strength, and they must stay separate:

- **Load-bearing, cannot fail:** no Run A answer cites a governed business definition, because none
  exists in the lakehouse. True by construction, every run.
- **Vivid, not guaranteed:** Run A's answers vary across runs. Show it, never depend on it.

Never build a beat on the second alone.

## Consequences for anything you propose

- No beat contains a scripted Run A answer. If you find yourself writing "Genie will say X," stop.
- Ambiguity in a demo question is usually the demonstration, not a bug. Do not "fix" a question to
  force the intended axis without checking the contract first.
- If a beat only works because of a data plant, change the beat. See the banned list in the
  contract, section 8. Every item on it was a real failure, not a hypothetical.
- Investigation comes before code. Probe first, write the script from transcripts, never from
  expectations. See `worklog/probe-run-a.md` for the format.
- Story 2 is out of scope for the current work. Do not touch it.

## Writing style for all docs in this project

No em-dashes. Use commas, colons, or restructure. Plain declarative prose, no emoji. Do not quote
counts, scores, or totals in prose: the numbers belong on screen at demo time, calculated live.

**Never cite line numbers.** Reference functions, named blocks, and dict keys instead:
`make_supply_relationships` in the generator, the `supply_relationships` entry in `upload.py`'s
SEMANTICS dict, `assert_betweenness` in `gds.py`. Line numbers in the worklog went stale within a
day and sent a reader to the wrong place.

**No demo artifact contains a value that a reseed would change.** The generator is RNG-driven and
Genie Agent is stochastic. See the reseed-invariance section in `worklog/CONTRACT.md`. Enforcement
is editorial: re-read what you changed before committing.
