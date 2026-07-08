# Fix plan: make the Q5/Q6 similarity method honest

## Problem

`gds.py` projects a customer graph, calls `gds.knn.stream`, prints the neighbor-pair
count, and then throws the kNN result away. The four similarity candidates are
actually chosen by a different computation: Euclidean distance to the risky-cohort
centroid. So the algorithm the code advertises is not the algorithm that produces the
answer.

This is algorithm theater. The kNN call is dead computation: its output is never
written back, never acted on, and never shown. In a demo the first question is "how
does the kNN pick those four?" and the honest answer is "it does not."

## Why nearest-centroid, not kNN

kNN and centroid distance answer different questions:

- **kNN** is node-to-node. It ranks customers by similarity to *each other* and yields a
  similarity graph. It does not rank nodes against a labeled group.
- **Nearest-centroid** is node-to-class. It ranks unlabeled customers by distance to the
  *center* of the known-risky cohort.

The Q5/Q6 question is "who is trending toward the known risky cohort before the rule
fires." That is a node-to-class question, so distance to the cohort centroid is the
metric that actually answers it. The centroid computation is correct for the task. The
only defect is dressing it up as kNN.

## Why this is the right call for the demo

The demo already earns its GDS claim once. Q4 is a genuine GDS algorithm: weighted
degree centrality over the projected `SUPPLIES` network, where the `gds.degree` output
is the numerator that is then normalized by degree to give exposure. Q5/Q6 does not need
to repeat a named GDS algorithm to make the "the graph finds the next ones" point. The
features live on the graph and the risky cohort is defined by a graph rule, so it stays a
graph story. It is a nearest-centroid classifier over graph-resident features, and naming
it that way is honest.

The alternative, forcing kNN to drive the selection through `SIMILAR_TO` edges, would be
methodologically clean but would change the planted data: the candidate set would then be
derived from graph structure, so `generate_data.py` and `ground_truth.json` would have to
be regenerated to match. That is more change and more risk for no added demo value given
Q4 already carries the GDS story. We keep the plant frozen and stay honest.

## The fix, file by file

Scope: `gds.py` plus the three docs that describe the method. No change to the generator,
the planted data, `ground_truth.json`, or `upload.py`.

### 1. `gds.py`

- Delete the kNN graph projection and the `gds.knn.stream` call in `compute_similarity`,
  along with the `SIMILARITY_GRAPH` constant, its `drop_graph` calls, and the
  neighbor-pair print line. The projection exists only to feed the discarded kNN call.
- Keep the customer feature read, the `similarity_vector` encoding, `find_risky_cohort`,
  the centroid computation, the distance ranking, and the assertion against
  `ground_truth`. These already reproduce the four candidates exactly.
- Change the write-back edge label `r.algorithm = 'knn'` to `r.algorithm = 'nearest-centroid'`.
- Rewrite the `reason` string to drop the word kNN, for example: "nearest the
  risky-customer cohort centroid; not yet tripping the last-3-invoices rule."
- Update the module docstring and the `compute_similarity` docstring and comments to
  describe nearest-centroid selection, not kNN.

Result: `compute_similarity` reads features, builds the risky-cohort centroid from the
last-3-invoices rule, ranks non-flagged customers by distance to that centroid, and takes
the four nearest. The GDS client is still used for Q4. Q5/Q6 uses it only as a Cypher
session for reads and the write-back, which is fine.

### 2. `README.md`

- Intro line: reword "Two Graph Data Science algorithms extend the rule-based answers" so
  it reads as one GDS algorithm for Q4 and one nearest-centroid similarity classifier for
  Q5/Q6.
- Section heading "The two GDS extensions": rename to something honest across both, for
  example "The two graph analytics extensions," and state which is GDS and which is a
  classifier.
- Q5/Q6 subsection: change "runs kNN over the payment-behavior features" to nearest-centroid
  distance to the risky cohort. In the `source:'gds'` query, the returned `cls.algorithm`
  value is now `nearest-centroid`, so update any prose that names it.

### 3. `DATA_ARCHITECTURE.md`

- "GDS Algorithms" intro: state one GDS algorithm plus one nearest-centroid classifier
  rather than "two Graph Data Science algorithms."
- "Customer similarity" subsection: replace the "Algorithm: k-Nearest Neighbors" line and
  the ELI5 with a nearest-centroid description. Keep the feature list and the reasons the
  features and `upsellScore` exclusion are what they are.
- Write-back section: the algorithm name recorded on the edge is now `nearest-centroid`.

### 4. `suppliers.md`

- Phase 5 body: the "kNN over payment-behavior features" bullet becomes nearest-centroid.
- Status line for Phase 5: reword the "runs deterministic kNN" phrasing to nearest-centroid
  so the status matches the code.

## What deliberately does not change

- **Q4 supplier risk propagation.** It is the genuine GDS algorithm and stays as written.
- **`generate_data.py` and `ground_truth.json`.** The planted cohorts and recorded
  distances stay frozen. The centroid method already matches them.
- **`upload.py`.** It reads `r.algorithm` generically, so the value flowing into the
  `classifications` gold table simply becomes `nearest-centroid`. No code change.
- **`source:'gds'` on the write-back edge.** `source` marks provenance of the analytics
  pass versus rule-planted edges. The analytics script is the GDS pass, since Q4 is real
  GDS, and the `algorithm` field already names the specific method. Keeping `source:'gds'`
  is honest and avoids rippling into `upload.py`, the README query, and the classifications
  contract. If we later prefer an algorithm-neutral marker, `source:'graph'` is the change,
  but it is out of scope here.

## Validation

- `python -m py_compile gds.py` passes.
- `uv run upload.py --check` and `uv run load.py --check` still pass.
- Offline reproduction from the CSVs still yields the four candidates
  CUST-072, CUST-025, CUST-082, CUST-073 with distances 0.258, 0.273, 0.277, 0.300,
  matching `gds_q5_similarity_candidates`. The centroid path is unchanged, so this holds.
- `grep -rniE 'knn|k-nearest|nearest neighbor|two (graph data science|gds)' supplier-risk-graph`
  returns nothing except intended history. The spelled-out forms matter: `DATA_ARCHITECTURE.md`
  writes "k-Nearest Neighbors" (no `knn` substring), and the "two GDS algorithms" framing lives in
  the README intro, the DATA_ARCHITECTURE intro, and `suppliers.md`. Run this before finishing to
  catch every residual reference in code and docs.
