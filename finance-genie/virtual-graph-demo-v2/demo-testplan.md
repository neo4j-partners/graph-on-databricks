# Virtual Graph Demo Test Plan

Tracks which Cypher and GDS queries actually work against the Finance Genie
**Neo4j Virtual Graph** (Aura graph-engine endpoint translating Cypher to SQL on
the backing Databricks warehouse), what has passed, what has failed, and how to
finish the testing safely.

Connection comes from the parent `finance-genie/.env`:
`NEO4J_URI=neo4j+s://<instance>.graph-engine.neo4j.io`.

## Goal

Establish the real translation boundary of the Virtual Graph so the demo and
`workshop/aura_gds_guide.md` describe what works rather than what is assumed to
work. The `✓`/`✗` markers in `queries.py` were inherited from the doc and do not
match observed behavior, so every query needs an empirical pass/fail.

## Harness hardening (applied)

`capability_probe.py` was hardened with the lessons from
`../virtual-graph-demo/test-vg-next.md` plus the failures seen here. The probe
now runs reliably two at a time.

1. **EXPLAIN by default.** A capability probe is a translation question: does the
   Virtual Graph turn this Cypher into SQL at all? `EXPLAIN` answers that without
   executing on the Databricks warehouse, so it cannot saturate the ~10-slot JDBC
   pool and cannot hang on a heavy aggregation. Unsupported syntax still surfaces
   as `42NG0`/`42NG1` at translate time. Every probe finished in 3 to 6 seconds.
   Use `--run` to execute for real (slower, pool-sensitive).
2. **No managed-transaction retry.** Each probe runs in an explicit
   `session.begin_transaction(timeout=...)` / `tx.run`. The managed
   `driver.execute_query` silently retries on a read timeout, which is what
   turned one slow query into the retry/DNS-failure storm that aborted the first
   full run.
3. **Broad exception catch.** Any failure (`Neo4jError`, `ServiceUnavailable`,
   socket errors) is recorded for that probe and the batch continues.
4. **Incremental results.** Each verdict is appended to `probe_results.jsonl`
   and stdout is flushed as it lands, so a mid-run failure leaves a partial
   record. Earlier runs lost everything to buffered stdout on kill.
5. **Pool health gate.** `RETURN 1` runs between probes; the batch stops if the
   pool degrades or after two timeouts.
6. **`load_dotenv(override=True)`.** The instance URI changes between sessions
   (`ge0d3851` then `ge5c674c` then `ge990841`); override picks up the current
   `.env` rather than a stale process value.

Two operational hazards from `test-vg-next.md` still hold and are the reason for
EXPLAIN and the two-at-a-time discipline: abandoning a slow client query does not
cancel it server-side (it keeps a pool slot until it finishes on Databricks), and
a few abandoned heavy queries saturate the pool with `HikariPool` errors.

> **zsh gotcha:** unquoted `$var` does not word-split in zsh. To pass a pair as
> two arguments in a loop, use `--only ${=pair}`, not `--only $pair`.

## Status summary

| Suite | Source | Status |
|-------|--------|--------|
| Plain-Cypher fraud queries (12) | `queries.py` via `main.py --all` | Complete |
| GDS pipeline (9 steps) | `gds_test.py` | Complete |
| Isolated feature probes (26) | `capability_probe.py` (EXPLAIN mode) | Complete |

## Results: plain-Cypher fraud queries

Run with `uv run main.py --all`. This run completed cleanly.

| # | Query | Marked | Observed | Failing construct |
|---|-------|--------|----------|-------------------|
| 1 | Fan-in (mule collection) | ✓ | **FAIL** `42NG0` | aggregating `WITH` + `count(DISTINCT)` + temporal arithmetic (also SLOW) |
| 2 | Fan-out (smurfing) | ✓ | **FAIL** `42NG0` | aggregating `WITH` + `count(DISTINCT)` |
| 3 | Pass-through mule | ✓ | **FAIL** `42NG0` | aggregation in `RETURN` over 2-hop path + duration arithmetic |
| 4 | Reciprocal / round-trip | ✓ | **PASS** (50 rows) | — |
| 5 | Layering cycles | ✗ | **FAIL** `42NG0` | variable-length path `->{2,4}` (expected) |
| 6 | Shared-merchant burst | ✓ | **FAIL** `42NG0` | aggregating `WITH` + `date(prop)` + `collect(DISTINCT)` |
| 7 | Structuring (just-under-threshold) | ✓ | **PASS** (0 rows) | — |
| 8 | New account, high velocity | ✓ | **FAIL** `42NG0` | `date() - duration({days:30})` temporal arithmetic |
| 9 | Hub network statistics | ✓ | **FAIL** `42NG0` | `count(DISTINCT)` + `OPTIONAL MATCH` + aggregating `WITH` |
| 10 | Rapid-turnover summary | ✓ | **FAIL** `42NG0` | 2-hop path + duration arithmetic + `avg(duration...)` |
| 11 | Velocity ratio | ✓ | **FAIL** `42NG0` | aggregating `WITH a, sum(t.amount)` |
| 12 | P2P-heavy, merchant-light | ✓ | **FAIL** `42NG0` | `count(DISTINCT)` + `OPTIONAL MATCH` + aggregating `WITH` |

Only **2 of 12** pass. Every failure is `Neo.ClientError.Statement.SyntaxError`
`42NG0: Unsupported syntax`, with the caret pointing at the aggregating `WITH`
(or the aggregating `RETURN` for queries 3 and 4's shape).

## Results: GDS pipeline

Run with `uv run gds_test.py`. This run completed cleanly. See the
"Confirmed: GDS does not run on the Virtual Graph" subsection of
`workshop/aura_gds_guide.md` for the writeup.

| GDS call | Observed |
|----------|----------|
| `gds.version()` | FAIL: `Aura Graph Analytics is versionless.` |
| `gds.graph.project('account_transfers', ...)` | FAIL `42NG0` |
| `gds.graph.list()` | PASS (0 rows) |
| `gds.pageRank.write(...)` | FAIL `42NG0` |
| `gds.louvain.write(...)` | FAIL `42NG0` |
| `gds.graph.project('account_merchants', ...)` | FAIL `42NG0` |
| `gds.nodeSimilarity.write(...)` | FAIL `42NG0` |
| `gds.graph.drop(...)` | PASS |

Projection and every algorithm write fail. `gds.graph.list`/`gds.graph.drop` are
recognized but there is nothing to list or drop. GDS is unavailable.

## Resolved: the translation boundary

The isolated EXPLAIN probes settle the open question. On instance `ge990841`,
**four constructs and only four** fail to translate. Everything else translates.

| Unsupported construct | Probe | Error |
|-----------------------|-------|-------|
| HAVING (`WHERE` after an aggregating `WITH`) | 5 | `42NG0: Unsupported syntax` |
| Temporal arithmetic inside a `WHERE` predicate | 15 | `42NG0: Unsupported syntax` |
| `OPTIONAL MATCH` | 21 | `42NG1: Unsupported syntax: OPTIONAL MATCH` |
| Variable-length path `->{2,4}` | 25 | `42NG0: Unsupported syntax` |

Findings that correct earlier assumptions:

- **`count(DISTINCT)` is supported** (probes 6 and 7), in both `WITH` and
  `RETURN`. The v2 fan-in/fan-out/hub queries did not fail because of
  `count(DISTINCT)`; they failed on the HAVING and temporal arithmetic that
  travelled with it.
- **HAVING genuinely fails** (probe 5). The earlier "Query 7 passes with a
  HAVING" observation came from a different instance (`ge5c674c`) and does not
  reproduce on `ge990841`. Treat HAVING as unsupported and apply thresholds
  client-side, as `../virtual-graph-demo/queries.py` already does.
- **Temporal arithmetic is position-sensitive.** `datetime() - duration({days: 7})`
  translates as a bare `RETURN` projection (probe 13) but fails as a `WHERE`
  predicate (probe 15). Plain timestamp comparison against a precomputed
  `$since` parameter is the supported pattern.
- **`OPTIONAL MATCH` is unsupported** here (probe 21, distinct `42NG1` code).
  This corrects `test-vg-next.md`, which assumed Q9 and Q12 were supported but
  slow; they were never cleanly parsed because the pool was saturated. Any query
  using `OPTIONAL MATCH` (Q9, Q12) needs a rewrite, not just a bigger warehouse.

## Isolated feature probes (complete)

Run with `capability_probe.py` in EXPLAIN mode. Full log in `probe_results.jsonl`.

| # | Feature | Verdict |
|---|---------|---------|
| 1 | baseline `MATCH` + `RETURN` prop | PASS |
| 2 | `WHERE` on raw node property | PASS |
| 3 | aggregation in `RETURN` (no `WITH`) | PASS |
| 4 | aggregating `WITH` then `RETURN` | PASS |
| 5 | aggregating `WITH` then HAVING-style `WHERE` | **FAIL** `42NG0` |
| 6 | `count(DISTINCT x)` in `WITH` | PASS |
| 7 | `count(DISTINCT x)` in `RETURN` | PASS |
| 8 | `sum()` in `WITH` | PASS |
| 9 | `round(sum())` in `WITH` | PASS |
| 10 | `avg()` in `WITH` | PASS |
| 11 | multiple aggregates in one `WITH` | PASS |
| 12 | `datetime()` literal | PASS |
| 13 | `datetime() - duration()` (projection) | PASS |
| 14 | `date()` literal | PASS |
| 15 | `WHERE` temporal arithmetic before `WITH` | **FAIL** `42NG0` |
| 16 | `date(property)` projection | PASS |
| 17 | two-hop path `RETURN` | PASS |
| 18 | reciprocal 2-cycle (query 4 shape) | PASS |
| 19 | `collect()` in `WITH` | PASS |
| 20 | `collect(DISTINCT)` in `WITH` | PASS |
| 21 | `OPTIONAL MATCH` | **FAIL** `42NG1` |
| 22 | undirected relationship pattern | PASS |
| 23 | `CASE` expression in `RETURN` | PASS |
| 24 | `DISTINCT` in `RETURN` (row-level) | PASS |
| 25 | variable-length path `{2,4}` | **FAIL** `42NG0` |
| 26 | two aggregating `WITH` chained | PASS |

## Next steps

1. **Reconcile the 12 fraud queries against the boundary.** Every failing query
   in `queries.py` fails only on HAVING, temporal arithmetic in `WHERE`,
   `OPTIONAL MATCH`, or a variable-length path. Adopt the
   `../virtual-graph-demo/queries.py` rewrites, which are already adapted:
   thresholds applied client-side, `$since` parameter for time windows,
   `OPTIONAL MATCH` removed or rephrased.
2. **Fix the `vg_compatible` flags** in this directory's `queries.py` so they
   match the probe verdicts rather than the inherited doc markers.
3. **Update `aura_gds_guide.md`.** The "What translates and what does not"
   section lists two failing patterns; add `OPTIONAL MATCH` and variable-length
   paths, and note the temporal-arithmetic position sensitivity (fails in a
   `WHERE`, works as a projection).
4. **Rewrite the four unsupported queries** (additional examples deliverable):
   - Q9 hub stats and Q12 P2P-vs-merchant: replace `OPTIONAL MATCH` with a
     directed pattern plus client-side handling of the missing side.
   - Q1, Q8: keep the `$since` parameter rewrite instead of `datetime()/date() -
     duration()`.
   - Any HAVING: aggregate and `ORDER BY` on the server, threshold client-side.
5. **Optional `--run` timings.** EXPLAIN confirms translation; a `--run` pass on
   a scaled-up warehouse would confirm the supported queries also execute in an
   acceptable time. Run those one or two at a time per the hazards above.

## Retest plan (completed) and how to rerun

The 26 probes were run two at a time in EXPLAIN mode against `ge990841`; all
returned a verdict and the pool stayed healthy throughout. To rerun a batch:

```bash
cd virtual-graph-demo-v2
PYTHONUNBUFFERED=1 uv run python -u capability_probe.py --only 1 2
# zsh loop over pairs (note ${=pair} for word-splitting):
for pair in "5 8" "6 7" "21 22"; do
  PYTHONUNBUFFERED=1 uv run python -u capability_probe.py --only ${=pair}
done
```

Verdicts append to `probe_results.jsonl`. The batches used, cheapest and most
diagnostic first:

| Batch | Probes | Question |
|-------|--------|----------|
| 1 | 1, 2 | baseline translation works at all |
| 2 | 3, 4 | aggregation in `RETURN` vs in `WITH` |
| 3 | 5, 8 | HAVING vs plain `sum()` in `WITH` |
| 4 | 6, 7 | `count(DISTINCT)` in `WITH` vs `RETURN` |
| 5 | 12, 13 | `datetime()` literal vs `datetime() - duration()` |
| 6 | 14, 15 | `date()` literal vs temporal arithmetic in `WHERE` |
| 7 | 16, 23 | `date(property)`; `CASE` |
| 8 | 17, 18 | two-hop path; reciprocal 2-cycle |
| 9 | 19, 20 | `collect()` vs `collect(DISTINCT)` |
| 10 | 21, 22 | `OPTIONAL MATCH`; undirected pattern |
| 11 | 9, 10, 11 | remaining aggregate shapes |
| 12 | 24, 25, 26 | row-level `DISTINCT`; variable-length path; chained `WITH` |

For real execution (`--run`), keep the slow full-graph aggregations (fan-in
shape) for last, run alone, and watch the post-probe health line.
