# Genie Demo Questions

Copy-paste ready. Run BEFORE questions in the Silver (unenriched) Genie Space; run AFTER and follow-on questions in the Gold (enriched) Genie Space.

---

## Primary Anchor: Merchant Favorites

### Before

```
Which merchants are most commonly transacted with by the top 10% of accounts by total dollar amount spent across merchants?
```

> Returns a flat popularity list — Brennan, Thomas and Dennis at 30 visits, Perry and Sons and Cox, Jimenez and Rodgers at 28 each. Plausible-looking chains, no triage priority.

### After

```
Which merchants show the highest concentration of ring-candidate transactions relative to the overall book? For the top 10, show each merchant's ring-candidate transaction share versus the ~5% baseline ring-candidate transaction share across the book.
```

> Ring-candidate accounts are ~5% of the book. At Brennan, Thomas and Dennis they generate 111 of the merchant's transactions from 70 accounts — roughly 7× over-represented. Alvarez-Barker shows the same pattern at 104 transactions from 68 accounts. The before answer names the same merchants but cannot show the disproportion; the after can.

### Follow-up: Before vs After Ranking Comparison

```
Rank the top 10 merchants by share of transactions from ring-candidate accounts. For each, also show where they rank among the top 10 merchants most visited by the top 10% of accounts by total spend, and flag whether they appear in both lists.
```

> Run in the Gold space. Produces a single table with both rankings side by side. Merchants that appear in both lists were accidentally caught by the volume proxy; merchants that appear only in the ring-candidate list are signal the proxy missed entirely. The overlap and the gaps are the demo's argument in one result.

---

## 5 Follow-On Questions (Gold Space)

### 1. Internal Transfer Circulation

```
For ring-candidate communities, what fraction of each community's total transfer volume flows between members inside the community versus to accounts outside? Show the top 5 communities by internal transfer ratio.
```

> Top communities show 93–95% of transfer volume staying inside the community — effectively a closed loop. Money enters, cycles between members, and exits through a small number of accounts. That is textbook layering behavior as a single queryable number.

### 2. Shared-Merchant Account Pairs

```
Which pairs of accounts have the highest similarity scores? Show the top 10 pairs with their similarity scores, whether they are in the same community, and their fraud risk tier.
```

> Node Similarity finds accounts that route through the same merchants even without ever transacting directly. Every top pair is in the same community and both accounts are high risk — two independent algorithms (Louvain and Node Similarity) land on the same accounts without being told to agree.

### 3. Investigator Work Queue

```
Show the top 15 accounts by risk score within ring-candidate communities. Include their community ID, region, total transaction volume, and fraud risk tier.
```

> Converts the structural signal into an actionable triage list. Risk score is PageRank eigenvector centrality — accounts at the center of money flow within the ring rank highest. All 15 returned accounts are high risk. This is the queue an investigator works from.

### 4. Book Exposure by Risk Tier

```
What is the total account balance held by high-risk tier accounts, and what share of the total book does that represent? Break it down by region.
```

> Puts a dollar figure on the structural signal. US-West leads at $57M in high-risk balances (5.4% of the regional book). Finance audiences always ask "how much money is at risk?" — this answers it by region.

---

## Validation Pair (run both, show side by side)

### Validation A Before

```
Which merchants are most commonly visited by the top 20 accounts by total transaction volume?
```

> Returns 243 merchants with no co-visit count above 2 — completely dispersed, nothing stands out.

### Validation A After

```
For James-Conway, Cardenas and Sons, Johnson, Williams and May, and Meyer Ltd, what share of each merchant's customers are members of ring-candidate communities, and how does that compare to the book baseline?
```

> Three sit at the ~4% book baseline (utilities, grocery, retail). James-Conway (crypto) is at 76% — ~19× above baseline. The before could not distinguish James-Conway from the noise; the after can.

---

## KYC: Shared-Identity Detection (Gold Space)

Run in the Gold space after `06_kyc_walkthrough` has landed the four KYC columns on `gold_accounts` (`shared_phone_count`, `shared_address_count`, `identity_cluster_id`, `identity_cluster_size`). These resolve against graph features computed by Weakly Connected Components over the shared phone and address graph, so they have no Silver equivalent. Finding who shares an identifier is a recursive self-join in the warehouse and a single column here.

### 1. Accounts Sharing a Phone

```
Which accounts share a phone number with another customer?
```

> Resolves to `gold_accounts.shared_phone_count > 0`. Returns the eight story-ring accounts (368, 927, 1033, 1696, 2184, 2216, 2612, 3003) and nothing else, because every background customer holds a unique number. The value is a graph feature: the count of other customers reached through the same `:Phone` node.

### 2. Accounts in a Shared-Identity Cluster

```
Show me accounts in a shared-identity cluster
```

> Resolves to `gold_accounts.identity_cluster_size > 1`. Returns the same eight accounts, all carrying one `identity_cluster_id` with `identity_cluster_size` = 8. No single phone connects all eight; the shared address is the bridge that collapses the two phone groups into one Weakly Connected Component. That traversal is what a warehouse cannot express in one hop.

> Both questions read from graph-derived columns. Money movement flagged the ring; identity resolution proves the eight accounts are one person wearing eight masks. See `KYC_DEMO.md` for the full walkthrough, including the knowledge-layer provenance query that names the policy, definition, and source columns behind the classification.
