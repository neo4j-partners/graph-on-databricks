# Genie Demo Questions

Copy-paste ready. Run BEFORE questions in the Silver (unenriched) Genie Space; run AFTER and follow-on questions in the Gold (enriched) Genie Space.

---

## Primary Anchor: Merchant Favorites

### Before

```
Which merchants are most commonly transacted with by the top 10% of accounts by total dollar amount spent across merchants?
```

> Returns a flat popularity list. Brennan, Thomas and Dennis has 30 visits.
> Perry and Sons and Cox, Jimenez and Rodgers each have 28. Many merchants
> receive equal triage priority.

### After

```
Which merchants show the highest concentration of ring-candidate transactions relative to the overall book? For the top 10, show each merchant's ring-candidate transaction share versus the ~5% baseline ring-candidate transaction share across the book.
```

> Ring-candidate accounts are about 5% of the book. At Brennan, Thomas and
> Dennis, they generate 111 transactions from 70 accounts. This rate is about
> seven times the baseline. Alvarez-Barker shows the same pattern with 104
> transactions from 68 accounts.

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

> Top communities keep 93% to 95% of transfer volume inside the community.
> Money enters, cycles between members, and exits through a small number of
> accounts. This ratio gives investigators a clear layering signal.

### 2. Shared-Merchant Account Pairs

```
Which pairs of accounts have the highest similarity scores? Show the top 10 pairs with their similarity scores, whether they are in the same community, and their fraud risk tier.
```

> Node Similarity finds accounts that use the same merchants. Every top pair is
> in the same community, and both accounts are high risk. Louvain and Node
> Similarity reach the same accounts from different graph patterns.

### 3. Investigator Work Queue

```
Show the top 15 accounts by risk score within ring-candidate communities. Include their community ID, region, total transaction volume, and fraud risk tier.
```

> Converts the structural signal into a triage list. PageRank gives higher risk
> scores to accounts at the center of the money flow. All 15 returned accounts
> are high risk.

### 4. Book Exposure by Risk Tier

```
What is the total account balance held by high-risk tier accounts, and what share of the total book does that represent? Break it down by region.
```

> Puts a dollar value on the structural signal. US-West leads with $57 million
> in high-risk balances, or 5.4% of the regional book.

---

## Validation Pair (run both, show side by side)

### Validation A Before

```
Which merchants are most commonly visited by the top 20 accounts by total transaction volume?
```

> Returns 243 merchants. Every co-visit count is two or lower, so the list has
> no clear outlier.

### Validation A After

```
For James-Conway, Cardenas and Sons, Johnson, Williams and May, and Meyer Ltd, what share of each merchant's customers are members of ring-candidate communities, and how does that compare to the book baseline?
```

> Three merchants match the 4% book baseline. James-Conway reaches 76%, which is
> about 19 times the baseline. The graph feature identifies the outlier.

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

> Both questions read from graph-derived columns. Money movement flags the ring.
> Identity resolution links the eight accounts to one shared identity. See the
> [KYC guide](../kyc-guide.md) for the full walkthrough and provenance query.
