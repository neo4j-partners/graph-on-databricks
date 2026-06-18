# Genie Space Reference

The Genie Spaces are provisioned and maintained by
`enrichment-pipeline/setup/provision_genie_spaces.py`. **That script is the source of
truth** for table lists, sample questions, and text instructions. Do not
edit the Genie Space instructions manually in the UI — the next provisioning
run wipes any manual edits (`replace_text_instruction` deletes all existing
instructions before adding the canonical one) and replaces them with the
content of `enrichment-pipeline/genie_instructions.md`.

This file is workshop-facing reading material — it explains where everything
comes from and what to expect when you run the live before/after reveal.

---

## Where things live

| What | Source of truth |
|------|-----------------|
| Table list attached to each space | `enrichment-pipeline/setup/provision_genie_spaces.py` — `BEFORE_TABLES`, `AFTER_TABLES` |
| Sample questions surfaced in the UI | same file — `BEFORE_QUESTIONS`, `AFTER_QUESTIONS` |
| Text instructions block | `enrichment-pipeline/genie_instructions.md` (lean — only table relationships and schema context) |
| Column-level documentation | Unity Catalog column comments, applied from the inline DDL in `05_pull_gold_tables.ipynb` sections 6–8 (mirrors `enrichment-pipeline/sql/gold_schema.sql`). Genie reads column descriptions directly from UC. |
| `fraud_risk_tier` / ring-size thresholds | `enrichment-pipeline/jobs/_gold_constants.py` — `RING_SIZE_LOW=50`, `RING_SIZE_HIGH=200`, `COMMUNITY_AVG_RISK_MIN=1.0` |

To change a column description, edit the DDL (either the workshop notebook
or `enrichment-pipeline/sql/gold_schema.sql` — keep them in sync) and re-run the
enrichment. Genie picks up the change on the next query.

---

## Tables in each space

**BEFORE space** (Silver only):
`accounts`, `merchants`, `transactions`, `account_links`

**AFTER space** (Silver + three Gold):
- Base: `accounts`, `merchants`, `transactions`, `account_links`
- Gold: `gold_accounts`, `gold_account_similarity_pairs`, `gold_fraud_ring_communities`

`account_labels` is intentionally **not** attached to either space. It holds
the ground-truth `is_fraud` column. If it were connected, Genie could
answer fraud questions by reading the label directly, which would make the
demo circular — Genie would find fraud because it sees the labels, not
because the graph features work. Ground-truth validation is handled
externally by `enrichment-pipeline/jobs/04_validate_gold_tables.py`, which joins
Gold against `ground_truth.json` outside Genie.

---

## Gold column semantics at a glance

`fraud_risk_tier` is **binary** — `'high'` when the account's Louvain
community has 50–200 members AND `community_avg_risk_score > 1.0`;
`'low'` for every other account. There is no `'medium'` tier.

`is_ring_candidate` on `gold_fraud_ring_communities` uses the same
predicate at the community level (`member_count` between 50 and 200 AND
`avg_risk_score > 1.0`).

Full column definitions are in the Unity Catalog comments. To read them:

```sql
DESCRIBE TABLE EXTENDED `graph-on-databricks`.`graph-enriched-schema`.gold_accounts;
DESCRIBE TABLE EXTENDED `graph-on-databricks`.`graph-enriched-schema`.gold_account_similarity_pairs;
DESCRIBE TABLE EXTENDED `graph-on-databricks`.`graph-enriched-schema`.gold_fraud_ring_communities;
```

---

## Before: Genie Without Graph Enrichment

This is what Genie returns when queried against the raw Silver tables — no GDS enrichment, no gold tables.

**Question asked:** "Are there accounts acting as hubs of potentially fraudulent money movement networks?"

**Genie's answer:** Yes — 20 accounts ranked by peer-to-peer transfer activity.

| Account | Outgoing Transfers | Incoming Transfers | Total Activity |
|---------|--------------------|--------------------|----------------|
| 13914 | 238 | 254 | 492 |
| 4342  | 241 | 237 | 478 |
| 16570 | 247 | 230 | 477 |
| 7429  | 247 | 228 | 475 |
| 7698  | 242 | 230 | 472 |

Genie's summary asked whether to identify hubs by transfer dollar amount instead — the SQL it ran ranked purely by transfer count over `account_links`.

**Why this answer is wrong:** The top 20 accounts land within 5% of each other on total activity (467 to 492). Every account here is a high-volume legitimate account — a payment aggregator or treasury account — not a fraud ring member. The actual fraud consists of 1,000 accounts organized into 10 rings of 100 members each, and none appear on this list. Fraud ring members transact at ordinary volumes and route through a shared set of anchor merchants; that pattern is invisible to a row-level COUNT over `account_links`.

The only signal Genie has in Silver is transfer count. Without community membership, risk-score centrality, or similarity-to-peers as columns, there is no way to separate high-activity whales from ring captains with coordinated peers.

---

## After: Genie With Graph Enrichment

This is what Genie returns once the GDS pipeline has run and `gold_accounts` carries `community_id`, `risk_score`, `is_ring_community`, and `similarity_score` as ordinary columns.

**Question asked:** "Are there accounts acting as hubs of potentially fraudulent money movement networks?"

**Genie's answer:** Yes — 20 accounts inside ring-candidate communities, ranked by PageRank `risk_score`.

| Account | Risk Score | Community | Community Size | Community Avg Risk |
|---------|------------|-----------|----------------|--------------------|
| 14268 | 14.71 | 15944 | 143 | 2.60 |
| 20129 | 3.89 | 18545 | 119 | 2.84 |
| 16205 | 3.86 | 18545 | 119 | 2.84 |
| 16579 | 3.82 | 7676  | 118 | 2.84 |
| 7890  | 3.80 | 4015  | 126 | 2.72 |

Seven distinct ring-candidate communities surface in the top 20, with community sizes clustered in the 118–143 band (the GDS ring-candidate size range). Account 14268 stands out as a sharp outlier in community 15944, with `risk_score` nearly 4× the next account in the list.

**Why this answer is correct:** Genie used `is_ring_community` to filter out the whales (whose high centrality is in the peer-to-peer transfer graph overall, not in ring-sized clusters) and then ranked by `risk_score` inside the filtered set. Community context — size, avg risk, `community_id` — gives the analyst an investigation handle: account 14268 is not "high risk" in isolation, it is "high risk inside a specific ring-sized community." Volume-based hub ranking cannot produce this answer because PageRank over the peer-to-peer transfer graph is a network quantity, not a row property.

---

## Demo Questions

Run BEFORE questions in the Silver (unenriched) Genie Space. Run AFTER and follow-on questions in the Gold (enriched) Genie Space.

### Warm-Up (BEFORE space)

```
What are the top 10 accounts by total amount spent across all merchants?
```

```
Which accounts have both above-average total spend and a night transaction ratio above 20%? Show the top 15 by total spend with their night ratio and account balance.
```

> Confirms Genie is working and can handle joins and conditional aggregates before the anchor runs.

---

### Primary Anchor: Merchant Favorites

**Before**
```
Which merchants are most commonly transacted with by the top 10% of accounts by total dollar amount spent across merchants?
```

> Returns a flat popularity list — Brennan, Thomas and Dennis at 30 visits, Perry and Sons and Cox, Jimenez and Rodgers at 28 each. Plausible-looking chains, no triage priority.

**After**
```
Which merchants show the highest concentration of ring-candidate transactions relative to the overall book? For the top 10, show each merchant's ring-candidate transaction share versus the ~5% baseline ring-candidate transaction share across the book.
```

> Top merchants show 80%+ ring-candidate transaction share vs the 5% book baseline — 16× over-represented. The before answer names the same popular chains but cannot surface the disproportion; the after can.

**Follow-up**
```
Rank the top 10 merchants by share of transactions from ring-candidate accounts. For each, also show where they rank among the top 10 merchants most visited by the top 10% of accounts by total spend, and flag whether they appear in both lists.
```

> Only 2 of the 10 highest-concentration ring merchants appeared in the volume-proxy top 10. The proxy missed 8 merchants entirely — the overlap and the gaps are the demo's argument in one table.

---

### Follow-On Questions (Gold space)

**1. Internal Transfer Circulation**
```
For ring-candidate communities, what fraction of each community's total transfer volume flows between members inside the community versus to accounts outside? Show the top 5 communities by internal transfer ratio.
```

> Top communities show 93–95% of transfer volume staying inside — a closed loop. Money enters, cycles between members, and exits through a small number of accounts. Textbook layering behavior as a single queryable number.

**2. Shared-Merchant Account Pairs**
```
Which pairs of accounts have the highest similarity scores? Show the top 10 pairs with their similarity scores, whether they are in the same community, and their fraud risk tier.
```

> Node Similarity finds accounts that route through the same merchants even without ever transacting directly. Every top pair is in the same community and both accounts are high risk — two independent algorithms agree on the same accounts without being told to.

**3. Investigator Work Queue**
```
Show the top 15 accounts by risk score within ring-candidate communities. Include their community ID, region, total transaction volume, and fraud risk tier.
```

> Converts the structural signal into an actionable triage list. Risk score is PageRank eigenvector centrality — accounts at the center of money flow rank highest. All 15 returned accounts are high risk.

**4. Book Exposure by Risk Tier**
```
What is the total account balance held by high-risk tier accounts, and what share of the total book does that represent? Break it down by region.
```

> US-West leads at $57M in high-risk balances (5.4% of the regional book). Puts a dollar figure on the structural signal.

---

### Validation Pairs

**Validation A: Merchant Ring-Candidate Share**

Before
```
Which merchants are most commonly visited by the top 20 accounts by total transaction volume?
```

> Returns 243 merchants with no co-visit count above 2 — completely dispersed, nothing stands out.

After
```
For James-Conway, Cardenas and Sons, Johnson, Williams and May, and Meyer Ltd, what share of each merchant's customers are members of ring-candidate communities, and how does that compare to the book baseline?
```

> Three sit at the ~4% book baseline (utilities, grocery, retail). James-Conway (crypto) is at 76% — ~19× above baseline. The before could not distinguish James-Conway from the noise; the after can.

---

**Validation B: High-Volume Account Community Membership**

Before
```
For the top 20 accounts by total transaction volume, how many unique merchants did each account visit?
```

> 7–21 unique merchants, no correlation with volume. Reads like legitimate diverse spending.

After
```
For accounts in the top 20 by total transaction volume, what is their community membership status and risk tier? Are those accounts concentrated in a small number of communities, or are they spread across the book?
```

> 19 of 20 are low risk, concentrated in two communities (21481, 19393). The enrichment confirms the before reading — high volume and diverse merchants is not a ring pattern here. The graph sometimes exonerates.

---

## Extended Demo Queries

Additional before/after pairs and Gold-space queries for deeper Q&A or extended demos. Use these when the audience wants to go further after the primary anchor.

### Backup Anchor: Ring Share by Region

**Before**
```
What share of accounts send more than half their transfer volume to five or fewer repeat counterparties, broken out by region?
```

> Flags 95.5%–96.3% of accounts in every region — no minority to triage.

**After**
```
What share of accounts sits in communities flagged as ring candidates, broken out by region?
```

> Flags 4.69%–5.51% per region — roughly a tenth the size of the proxy minority. Concentration does not imply coordination; only the graph separates them.

---

### Book Share

**Before**
```
For the top 10% of accounts by transfer volume, what is the total balance held and what share of the book do they represent?
```

**After**
```
For ring-candidate communities taken together, what is the total balance held by their members and what share of the book do they represent?
```

---

### Internal vs External Transfer Ratio

**After**
```
For each ring-candidate community, what is the ratio of internal transfer volume between members to external transfer volume outside the community?
```

---

### Merchant Community Concentration

**After**
```
Are there merchants whose customer base is disproportionately concentrated in a single community?
```

---

### Fraud Hub Detection

**Before**
```
Are there accounts acting as hubs of potentially fraudulent money movement networks?
```

**After**
```
Are there accounts acting as hubs of potentially fraudulent money movement networks?
```

> Before returns the 20 highest-activity whales, all within 5% of each other. After filters to ring-community members and ranks by `risk_score`, surfacing account 14268 as a sharp outlier at 14.7 vs ~3.8 for the rest.

---

### Fill-In / Q&A (Gold space)

```
How does total account balance split between the high and low risk tiers?
```

```
How many distinct communities are there, and what is the distribution of community sizes?
```

```
What fraction of transfer volume flows between accounts in the same community versus across communities?
```

```
For accounts in ring-candidate communities, what fraction of their transfer volume stays within the community versus flows outside it, compared to non-ring accounts?
```

```
How does the distribution of risk scores differ between ring-candidate and non-ring accounts?
```

```
What is the average transfer count per account within ring-candidate communities versus the general account population?
```

```
Break down the ring-candidate community set by region: how many candidates sit primarily in each region, and what is their average member count?
```

```
Which regions have the highest concentration of accounts in ring candidate communities per thousand accounts?
```

```
Which merchants show the largest gap between the risk-tier composition of their customer base and the risk-tier composition of the overall account population?
```

```
For each merchant category, what share of transaction volume comes from accounts in the high-risk tier?
```
