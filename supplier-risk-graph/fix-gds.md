# Fix plan: make Q5/Q6 a genuine, emergent GDS kNN finding

## Problem

`gds.py` projects a customer graph, calls `gds.knn.stream`, prints the neighbor-pair
count, and throws the result away. Selection is done by a different computation: Euclidean
distance to the risky-cohort centroid. The algorithm the code advertises is not the
algorithm that produces the answer.

The dishonesty runs one layer deeper than the code. `generate_data.py` (`evaluate_gds`,
lines 601-622) computes `gds_q5_similarity_candidates` with the *same* centroid proxy, so
the recorded ground truth is the output of a hand-rolled centroid calc, not of any GDS
run. No kNN output influences the Q5/Q6 result at any layer, code or ground truth. The kNN
call is pure theater.

## Goal

Q5/Q6 becomes a real GDS kNN finding whose answer *emerges from the algorithm*: run kNN,
let it pick the candidates, show them. The data is fixed-seed and kNN is deterministic, so
the result is stable across runs without an exact-value ground-truth freeze.

This gives the demo two genuine GDS algorithms: Q4 weighted degree centrality and Q5/Q6 kNN
similarity. Q4 already earns the GDS claim; this makes Q5/Q6 earn it too, with a stronger
graph story than centroid distance because the answer comes from similarity-graph structure
(who is a near neighbor of the known-risky customers), not from distance to a mean.

## Design

Selection:

1. Build the kNN similarity graph over the four encoded features (`avgDaysLate`,
   `overdueShare`, `churnRisk`, `profitabilityTrend`; `upsellScore` still excluded). This
   yields SIMILAR_TO neighbor pairs with a similarity score.
2. Identify the risky cohort with the existing rule (`find_risky_cohort`, last-3-invoices
   over the 60-day threshold).
3. Candidates are the non-flagged customers that are kNN neighbors of risky-cohort members,
   ranked by max similarity to any risky member, taking the top `N_SIMILAR` (4). The
   interpretable line for the demo: "the customers the similarity graph places nearest to
   the known-risky ones, that do not yet trip the rule."

Determinism: run GDS kNN with `concurrency=1`, `sampleRate=1.0`, a fixed `randomSeed`, and
an explicit similarity metric (Euclidean over the four-feature vector; do not rely on the
GDS default for a float-list property). Ties break by internal node id, reproducible on the
same fixed-seed projection.

No exact-value ground-truth freeze for Q5. Assert only a shape invariant so gross breakage
still fails loud: exactly four candidates, all non-flagged, each with at least one risky
neighbor.

## The fix, file by file

### 1. `gds.py`

- `compute_similarity`: keep the feature read, `find_risky_cohort`, the kNN projection, and
  the `gds.knn.stream` call, but now *use* the result. Delete the centroid computation and
  the `distance` ranking. Rank the risky cohort's kNN neighbors by similarity and take the
  top four. Set `concurrency=1`, `sampleRate=1.0`, fixed `randomSeed`, explicit metric.
- `write_similarity`: `r.algorithm = 'knn'` is now true and stays. `r.score` becomes the kNN
  similarity score (higher is more similar). Rewrite `r.reason` to describe the kNN
  neighbor-of-risky finding, dropping the centroid wording.
- `assert_similarity`: replace the exact-value comparison against `ground_truth` with the
  shape invariant (four candidates, all non-flagged, each with a risky neighbor).
- Remove `similarity_vector`, `CHURN_SCALE`, `TREND_SCALE` if nothing else uses them after
  the centroid math is gone.
- Update the module docstring and `compute_similarity` docstring/comments to describe two
  genuine GDS algorithms and the emergent kNN selection.

### 2. `generate_data.py`

- `evaluate_gds`: remove the Q5 centroid block (lines 601-622) and the local `similarity`
  return. Keep the Q4 exposure proxy: mean supplier risk per business unit maps exactly to
  the GDS degree-centrality result, so it stays a valid offline ground truth.
- Remove the module-level `similarity_vector` helper (lines 560-566) and the
  `CHURN_SCALE`/`TREND_SCALE` scales if unused after that.
- Ground-truth emission (lines 756-782): stop writing `gds_q5_similarity_candidates`.
- Keep the `similar` cohort plant (lines 205-209) as a feature-shaping device: it seeds a
  believable population of near-risky customers for kNN to find. Add a comment that it
  shapes the feature distribution but no longer defines the Q5 answer. The emergent top-four
  may or may not equal the planted `similar` set; that is expected and fine.

### 3. `README.md`

- Intro (line 5): reword "Two Graph Data Science algorithms extend the rule-based answers"
  so both are genuine GDS; Q5/Q6 is kNN similarity whose answer emerges from the run.
- "The two GDS extensions" (line 207): Q5/Q6 subsection describes the kNN SIMILAR_TO graph
  and risky-neighbor ranking. The `source:'gds'` write-back and `algorithm:'knn'` are now
  literally accurate, so prose naming them is correct as written.
- Hard-coded Q5 candidate IDs (line 246 "Expected: 4 candidates..." and the line 261 results
  table row) are refreshed from the actual run, not left as CUST-072/025/082/073. The wording
  also drops "close to the known risky cohort" phrasing in favor of the kNN-neighbor framing.

### 4. `DATA_ARCHITECTURE.md`

- Intro (line 88): keep "two Graph Data Science algorithms"; it is now true for both.
- "Algorithm: k-Nearest Neighbors" (line 102): keep the name and correct the description to
  a node-to-node similarity graph feeding a risky-neighbor ranking, with the answer emerging
  from the run rather than a planted set.

### 5. `suppliers.md`

- Phase 5 body and status line (and the Phase 1 rev note, line 16): Q5/Q6 runs real GDS kNN;
  the answer is emergent, not asserted against a frozen Q5 key; the Q5 candidates are no
  longer in `ground_truth.json`. Drop the "nearest the risky-cohort centroid" and
  "deterministic kNN ... then classifies the four nearest the centroid" wording, and refresh
  the hard-coded CUST-072/025/082/073 list (line 20) from the actual run.

## What deliberately does not change

- **Q4 supplier risk propagation.** Genuine GDS, unchanged, keeps its exact ground-truth
  assertion.
- **`find_risky_cohort`, `N_SIMILAR = 4`, the four encoded features, the `upsellScore`
  exclusion.** The rule-defined cohort and the feature set stay.
- **`upload.py`.** It reads `r.algorithm` generically; the value is now a truthful `'knn'`.
  No code change.
- **`source:'gds'` on the write-back edge.** Now literally correct: the pass is real GDS.

## Validation

- `python -m py_compile gds.py` passes. `uv run upload.py --check` and `uv run load.py
  --check` still pass.
- On the target Aura + GDS instance: run `gds.py` and confirm a clean top-four with real
  separation (no fragile near-ties that would make the demo brittle), then run it again and
  confirm identical output (determinism). Note the four companies for the demo talk track.
- `grep -rniE 'centroid|distance_to_risky|nearest.centroid' supplier-risk-graph` returns
  nothing in code or docs except intended history: the centroid method is fully gone from
  both `gds.py` and `generate_data.py`.
- `grep -rniE 'knn|k-nearest|two (graph data science|gds)' supplier-risk-graph` shows both
  algorithms described as genuine GDS, with no leftover "runs kNN then ranks by centroid"
  wording.

## Decisions to confirm

1. **Ranking rule:** max similarity to any risky member (recommended), versus count of risky
   members in a customer's top-k, versus mean similarity to the cohort.

Data is regenerated as part of this change, so the four surfaced companies will simply be
whatever kNN produces on the new data; there is no old set worth preserving. But the current
four IDs are hard-coded in the docs (`README.md` lines 246 and 261, `suppliers.md` lines 16
and 20), so those must be refreshed from the actual run once the change lands, not left as
CUST-072/025/082/073. Q4's BU-03 references are unchanged and stay valid.
