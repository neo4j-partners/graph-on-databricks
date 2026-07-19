# graph-on-databricks — CLAUDE.md

This repo holds several independent Databricks projects. Read the subproject's own `CLAUDE.md`
before working in it.

## supplier-risk-graph

`supplier-risk-graph/CLAUDE.md` is required reading before proposing anything about that demo, and
`supplier-risk-graph/proposals/CONTRACT.md` is the authority for its narrative, questions, beats, and
data topology.

The point that gets misread most often, repeated here so it is visible from the repo root: the demo
is **ungrounded versus grounded**, not wrong versus right. Genie Agent is a frontier LLM over
tables and its answers are plausible, defensible, and anchored to nothing. **Do not predict what
Genie will answer, and do not engineer data so a predicted answer is wrong.** That approach is
unwinnable against a stochastic generator and it is the largest source of wasted work in this
project's history.
