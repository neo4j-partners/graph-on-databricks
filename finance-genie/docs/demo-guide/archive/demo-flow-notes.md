# Demo Flow

> **Core goal of this rewrite:** Don't explain the enrichment pipeline before showing the payoff. Lead with one fraud question and two answers, before and after enrichment, and let the gap speak for itself. The anchor question must produce a difference that is immediately legible on common sense alone, without graph-theory knowledge. The before answer should sound plausible but be structurally wrong; the after answer should be specific and actionable. The audience's question, "how did you get that?", is the invitation to explain the architecture. The explanation earns its place because they asked for it.
>
> **Framing: expansion, not limitation-recovery.** Pitch the enriched lakehouse as unlocking a new set of questions for Genie, not as patching a Genie shortcoming. The before/after is a demonstration of that unlock; it is not an argument that Genie is broken.
>
> **Time budget: 15 minutes, three parts: anchor, architecture, pipeline.** The anchor opens with the before/after question and its two answers. The architecture section explains what Neo4j adds. The pipeline section shows how the features that produced the second answer are built. Question selection needs to respect this envelope. An anchor that requires setup before the two answers make sense does not fit.
>
> **Reference shape for the gap: the FINRA demo.** Phillip's FINRA demo for the Wells Fargo investment community asked which asset managers were most exposed to the Iran conflict. Without graph RAG, Genie returned descriptors such as funds with high oil exposure and funds with high defense exposure. With graph RAG, it returned the actual top 10 asset managers by name. Descriptors vs. named entities is the model of a legible gap. If the before/after on a candidate question is not as visible as that, keep looking.


# Current Flow

**Anchor**

1. **Fraud doesn't happen in one account:** Money laundering rings, mule operations, and coordinated schemes spread activity across dozens of accounts, deliberately, to evade per-account detection. The scheme is a shape: a cluster of accounts moving money densely among themselves. Each transaction looks clean in isolation; the pattern across accounts does not. A row-level aggregation cannot produce a property that only exists in the connections between accounts.

   *Alternative framing, **Coordinated schemes hide between the rows**:* Structuring, layering, and mule networks intentionally split activity across many accounts so no single account trips a threshold. The scheme is in the movement *between* accounts, not in any row. Row-level detection cannot produce that network property.
2. **Demo data set, two overlapping networks:** The synthetic banking dataset contains two networks that share accounts. The spending graph links accounts to merchants; the peer-to-peer transfer graph links accounts to other accounts. Fraud rings leave footprints in both: tight clusters of accounts that trade with each other and route through the same merchants. The goal of the demo is not to label fraud on any one row; it is to make those cross-account shapes visible as columns the analyst can query. Silver data model diagram anchors the slide.
3. **Merchant favorites, the anchor question:** Run "Which merchants are most commonly transacted with by accounts in ring-candidate communities?" against the raw lakehouse (before) and the enriched lakehouse (after). Before: top merchants by overall visit count, popular chains that sound like a real answer. After: a specific list of merchants where ring-community members cluster disproportionately. Show both side by side; let the audience evaluate the gap without domain expertise required; no architecture yet.

   *Presenter cue: hold on the two answers until someone asks "how did you get that?" That question is the invitation into Architecture. If nobody asks, offer it: "does anyone want to know how we got to that specific list of merchants?"*

**Architecture**

4. **What graph analysis adds to Genie:** Three new kinds of answers that don't exist as row-level properties. Centrality captures how central an account is in the flow of money. Community captures which accounts cluster tightly together. Similarity captures which accounts route through the same counterparties. Each is a network property that graph analysis produces and the lakehouse then lands as a column. Framed as: this is what the graph unlocks for Genie.
5. **Graph databases find every instance of a pattern:** Describe a shape, such as a cluster of accounts moving money densely among themselves or accounts sharing the same counterparties, and the graph returns every place that shape exists in the network. No starting account, no ID to look up. Pattern-matching is the graph's native operation, which is why connection questions live there.
6. **Better columns for better Genie answers:** Graph-derived columns like `risk_score`, `community_id`, `similarity_score`, and `fraud_risk_tier` land in Gold alongside `region`, `product`, and `balance`. Genie treats them like any other dimension: `GROUP BY fraud_risk_tier`, `WHERE is_ring_candidate = true`. Same Genie, same SQL, new questions unlocked. Change the columns; change what Genie finds.

**Pipeline**

7. **Architecture at a glance:** Silver tables load into Neo4j Aura as a property graph; GDS computes PageRank, Louvain, and Node Similarity; Databricks pulls the results back via the Spark Connector, joins against Silver, and materializes `risk_score`, `community_id`, and `similarity_score` as Delta columns in Gold. The pull direction matters: Neo4j does not write to Unity Catalog; nothing in the graph reaches a Genie query except what Databricks has already materialized to Gold. `gold_accounts` and `gold_account_similarity_pairs` are the two Gold tables that feed the after demo.
8. **Load Silver into Neo4j:** Account and transaction records from the existing lakehouse map into Neo4j Aura as a network of connected entities.
9. **Run GDS, patterns become columns:** PageRank surfaces accounts central to money flow, producing `risk_score`. Louvain finds clusters trading tightly together, producing `community_id` and `fraud_risk_tier`. Node Similarity finds accounts sharing the same counterparties, producing `similarity_score`. Same graph in, same scores out, every time.
10. **Enrich, results land in Gold:** Databricks pulls GDS outputs from Neo4j via the Spark Connector, joins with Silver, and writes `risk_score`, `community_id`, and `similarity_score` as plain Delta columns.
11. **Query: auditable by construction.** Nothing in the graph reaches a Genie query until the pipeline has materialized it into the enriched Gold tables. Genie treats graph-derived columns as ordinary dimensions; the audit trail is the Delta table.

**Close**

12. **The graph finds candidates; the analyst finds fraud:** GDS produces structural signals that indicate *ring-like behavior*: community membership, centrality, similarity. Deciding which accounts and merchants warrant investigator time is the analyst's job, done by running ordinary Genie queries against the enriched Gold tables. The "after" questions in this demo cover merchant concentration, regional review workload, and book share by community. That *is* the workflow.
13. **The analyst's toolkit, expanded:** Graph-derived columns unlock a class of questions the analyst couldn't frame against the lakehouse alone: sizing the candidate-ring population as a share of the book, triaging investigator workload by region or risk tier, comparing cohorts defined by community membership against the baseline, and looking at merchants through the lens of their customers' structural signals. The analyst works in Genie the same way they always have. The difference is that `community_id` and `risk_tier` are now available as ordinary dimensions alongside region, product, and balance. `GROUP BY fraud_risk_tier`, not "find the ring." Framed as expansion, not limitation recovery.
14. **Key takeaways:** One question, two answers: the gap is the whole argument. Graph for connection questions; lakehouse for everything Genie already does well. GDS columns land in Gold as ordinary dimensions, so the analyst's toolkit gets bigger, not different.

**Fill-in / Q&A**

15. **Generalization:** The pattern applies beyond fraud: entity resolution, supplier-network risk, recommendation, compliance review
16. **Defensibility:** GDS produces features with published mathematical definitions; humans and downstream models adjudicate, not the pipeline
17. **Genie on the base catalog:** Before enrichment, Genie answers standard BI questions against the raw catalog: top accounts by total spend; accounts with above-average spend and more than 20% of transactions at night. Genie is doing its designed job on the customer's existing tables. The enrichment is expansion, not repair.
18. **Deterministic columns under a non-deterministic translator:** Genie generates different SQL each run: `RANK()=1` one time, `LIMIT 100` the next. GDS outputs are fixed: same projection, same scores, every time. SQL variance only changes how much signal Genie surfaces, never whether it exists. The reliable combination is a deterministic column inventory beneath a non-deterministic translation layer.
19. **Backup anchor, ring share by region:** If Merchant Favorites doesn't land, the alternate before/after asks what share of accounts look ring-like by region. The volume-proxy flags 95.5% to 96.3% of accounts in every region, with no minority to triage. The enriched version flags 4.69% to 5.51%, a structurally defined minority roughly a tenth the size of the proxy minority.
20. **Validation, merchant ring-candidate share:** Before asks which merchants the top 20 highest-volume accounts visit most; the answer is 243 merchants with no visit count above 2, completely dispersed, no merchant stands out. After measures each candidate merchant's ring-candidate customer share against the ~4% book baseline. Three of four candidates sit at baseline; James-Conway (crypto) is ~19× above it. The before answer could not distinguish the outlier from the noise; the after answer can.
21. **Validation, high-volume accounts exonerated:** Before observed that top-volume accounts visit many merchants, 7 to 21 each with no correlation with volume, which reads like diverse spending. After confirms it: 19 of 20 top-volume accounts are low risk, concentrated in three known low-risk communities. The enrichment validates the before reading rather than overturning it; the graph sometimes exonerates. See the "Refined After" section for the underlying query and full result.

# Finding Candidate Rings

The graph finds suspicion; the analyst finds fraud. GDS turns network structure into columns like community membership, centrality, and similarity that flag accounts whose *shape of activity* resembles a ring. It does not prove fraud; the pipeline makes no judgment call. A high-risk community is a candidate, not a verdict. The fraud work is an analyst running ordinary Genie queries against the enriched Gold tables: sizing the candidate population, scoping investigator workload by region, comparing cohorts by risk tier, deciding which accounts and merchants warrant review. The demo's "after" questions are that workflow: traditional analytics conditioned on graph-derived columns.

---

# Anchor Question Core Goal

The before and after questions are not the same question rephrased. They are two questions an analyst would actually ask while hunting fraud, paired so the gap between them is the value of the enrichment.

The before question is a real fraud-hunting question an analyst asks today against the Silver tables. It uses the proxies analysts have no choice but to use when the only signal available is volume, count, frequency, or balance: "who are the highest-volume accounts," "which merchants have concentrated customer bases," "what is the regional distribution of large-transfer accounts." These are reasonable questions. They produce answers that sound useful. They are also structurally blind to coordination across accounts, because no row-level column encodes it.

The after question is what the same analyst would ask if `community_id`, `risk_tier`, and `similarity_score` were sitting in Gold next to `region` and `balance`. It is not a rewrite of the before question with a graph column swapped in. It is the richer question the analyst could not frame at all before the enrichment existed: sizing a candidate-ring cohort, scoping investigator workload by risk tier, comparing internal-to-external transfer ratios within a community, finding merchants whose customer base skews structurally rather than by volume. The after question should be specific enough that the answer is a list, a number, or a named cohort the analyst can act on, not a descriptor.

The gap between the two answers is the argument. The before answer describes the book; the after answer identifies a target. If a candidate pairing does not produce that kind of gap, it does not belong in the anchor set.


# Final Set of Anchor Questions

Each candidate rephrased so the before question is askable against Silver tables without graph columns, and the after question uses the Gold-layer column the before could not reach. The before uses volume, count, or frequency as a proxy; the gap between the two answers is the demo's argument.

1. **Merchant favorites**
   - Before: "Which merchants are most commonly transacted with by the top 10% of accounts by total dollar amount spent across merchants?"
   - After: "Which merchants are most commonly transacted with by accounts in ring-candidate communities?"
   - Follow-up: "Which ring-candidate communities have the highest total transaction volume, and how many member accounts do they contain?"
   - Follow-up: "What share of total book transaction volume do the top 5 ring-candidate communities account for?"
   - Follow-up: "For accounts in the ring-candidate communities with the highest transaction volume, which merchants do they visit most?"

2. **Ring candidate book share**
   - Before: "For the top 10% of accounts by transfer volume, what is the total balance held and what share of the book do they represent?"
   - After: "For ring-candidate communities taken together, what is the total balance held by their members and what share of the book do they represent?"

3. **Ring share of the book by region**
   - Before: "What share of accounts send more than half their transfer volume to five or fewer repeat counterparties, broken out by region?"
   - After: "What share of accounts sits in communities flagged as ring candidates, broken out by region?"

4. **Investigator review queue**
   - Before: "How many accounts are in the top 10% by transfer volume, and what is the regional breakdown of that workload?"
   - After: "How many accounts would need investigator review if the bar is high risk tier, and what is the regional breakdown of that workload?"

5. **Per-community internal vs external transfer ratio**
   - Before: "For each account, what is the ratio of transfer volume sent to its top three counterparties versus everyone else, and how does that ratio distribute across the book?"
   - After: "For each ring-candidate community, what is the ratio of internal transfer volume between members to external transfer volume outside the community, and how does that ratio distribute across the candidate set?"

6. **Transfer count cohort**
   - Before: "What is the average transfer count per account among accounts whose top three counterparties account for more than half their transfer volume, versus the general account population?"
   - After: "What is the average transfer count per account within ring-candidate communities versus the general account population?"

7. **Merchant spend mix by cohort**
   - Before: "How does merchant-category spending mix differ between the top 10% of accounts by transfer volume and the baseline?"
   - After: "How does merchant-category spending mix differ between ring-community accounts and the baseline?"

8. **Merchant community concentration**
   - Before: "Which merchants have a customer base concentrated in fewer than 20 accounts that together make up more than half of their transaction volume?"
   - After: "Are there merchants whose customer base is disproportionately concentrated in a single community?"

9. **Same-community transfer volume share** *(validated: works well. Proxy says ~14% of volume is in repeat-pair relationships; the graph shows ~76% of volume stays within community. Proxy under-counts structural coordination by 5x.)*
   - Before: "What fraction of total transfer volume flows between accounts that have transacted together 5 or more times, versus accounts with no prior transaction history?"
   - After: "What fraction of transfer volume flows between accounts in the same community versus across communities?"

---

# Refined After

These are follow-up queries run against the enriched Gold tables to test whether the before interpretations hold once community membership and risk tier are available as dimensions. Both have been validated against the enriched Genie space.

**Spread-across-merchants behavior: validated**

The before answer observed that top-volume accounts spread activity across many unique merchants, with account 13318 ($18,429) visiting 9 and account 11764 ($11,267) visiting 21, and no correlation between volume and merchant diversity.

Query:
> "For accounts in the top 20 by total transaction volume, what is their community membership status and risk tier? Are those accounts concentrated in a small number of communities, or are they spread across the book?"

Result: 19 of 20 top-volume accounts are low risk. They concentrate in three communities (16163, 6049, 3040) with only one high-risk account (3404, community 3040). The before interpretation was correct: diverse merchant visits among high-volume accounts is a legitimate pattern, not a layering signal. Spreading across 243 distinct merchants with maximum per-merchant visit count of 2 across the entire cohort confirms these accounts are not coordinating. The enrichment validates the before reading rather than overturning it.
