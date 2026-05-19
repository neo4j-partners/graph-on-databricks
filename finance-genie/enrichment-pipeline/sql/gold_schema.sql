-- Gold table schema for the graph-enriched finance pipeline.
--
-- Defines the three gold tables written by pull_gold_tables.py, with
-- Unity Catalog column-level comments. Column descriptions are the primary
-- signal Genie uses to understand what each column means.
--
-- Executed by pull_gold_tables.py before writing data, on every pipeline run.
-- Placeholders ${catalog} and ${schema} are substituted at runtime.
-- ${catalog} resolves to the gold catalog (GOLD_CATALOG, falling back to
-- the legacy single CATALOG when GOLD_CATALOG is unset).
--
-- Schema is intentional and versioned here. Any column change (name, type,
-- description) must be reflected in both this file and pull_gold_tables.py.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.gold_accounts (
    account_id               BIGINT   NOT NULL COMMENT 'Account identifier (joins to accounts.account_id)',
    account_hash             STRING   COMMENT 'Anonymized account identifier',
    account_type             STRING   COMMENT 'Account category: checking, savings, or business',
    region                   STRING   COMMENT 'Geographic region where the account was opened',
    balance                  DOUBLE   COMMENT 'Current account balance in USD',
    opened_date              DATE     COMMENT 'Date the account was opened',
    holder_age               INT      COMMENT 'Age of the account holder in years',
    risk_score               DOUBLE   COMMENT 'PageRank centrality score on the account-to-account transfer graph. Measures how influential an account is in the transfer network. Null for accounts below the minimum degree threshold.',
    betweenness_centrality   DOUBLE   COMMENT 'Sampled Betweenness centrality score on the account-to-account transfer graph. Measures how often an account sits on shortest paths between other accounts. Null for accounts below the minimum degree threshold.',
    community_id             BIGINT   COMMENT 'Louvain community label. Accounts that predominantly transfer money among themselves share the same community_id. Null for accounts below the minimum degree threshold.',
    similarity_score         DOUBLE   COMMENT 'Jaccard similarity score from the shared-merchant bipartite graph. Measures overlap in merchant visit patterns with other accounts in the same community. Null for accounts below the minimum degree threshold.',
    community_size           BIGINT   COMMENT 'Number of accounts sharing this community_id',
    community_avg_risk_score DOUBLE   COMMENT 'Mean risk_score across all accounts in the community',
    community_risk_rank      INT      COMMENT 'Rank of this account within its community, ordered by similarity_score descending, then risk_score descending, then account_id ascending. Rank 1 = the account with the highest merchant-overlap similarity in the community.',
    inbound_transfer_events  BIGINT   COMMENT 'Count of account_links rows where this account is the transfer destination (dst_account_id)',
    txn_count_30d            BIGINT   COMMENT 'Count of merchant transactions for this account in the most recent 30 days present in the dataset',
    distinct_merchant_count_30d BIGINT COMMENT 'Count of distinct merchants visited by this account in the most recent 30 days present in the dataset',
    distinct_counterparty_count BIGINT COMMENT 'Count of distinct accounts this account sent funds to or received funds from across the account_links window',
    is_ring_community        BOOLEAN  COMMENT 'True when the account community has between 50 and 200 members and a community_avg_risk_score above 1.0, indicating a tightly-knit transfer cluster of anomalous size and centrality',
    fraud_risk_tier          STRING   COMMENT 'Pre-computed binary risk classification based on community membership. Values: high (is_ring_community=true — the account belongs to a tightly-knit transfer cluster of anomalous size and centrality), low (all other accounts).'
)
USING DELTA
COMMENT 'Account dimension enriched with graph analytics features derived from the transfer network';

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.gold_account_similarity_pairs (
    account_id_a     BIGINT   COMMENT 'First account in the pair, always the smaller account_id (joins to gold_accounts.account_id)',
    account_id_b     BIGINT   COMMENT 'Second account in the pair, always the larger account_id (joins to gold_accounts.account_id)',
    similarity_score DOUBLE   COMMENT 'Jaccard similarity score based on shared merchant visits between account_id_a and account_id_b',
    same_community   BOOLEAN  COMMENT 'True when account_id_a and account_id_b share the same non-null community_id in gold_accounts'
)
USING DELTA
COMMENT 'Account pairs connected by a shared-merchant similarity edge — one row per unique pair';

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.gold_fraud_ring_communities (
    community_id           BIGINT   COMMENT 'Community identifier (joins to gold_accounts.community_id)',
    member_count           BIGINT   COMMENT 'Number of accounts in this community',
    avg_risk_score         DOUBLE   COMMENT 'Mean graph centrality score across all community members',
    max_risk_score         DOUBLE   COMMENT 'Highest graph centrality score within the community',
    avg_similarity_score   DOUBLE   COMMENT 'Mean merchant-visit similarity score across community members',
    high_risk_member_count BIGINT   COMMENT 'Number of accounts in this community with risk_score above 1.0',
    is_ring_candidate      BOOLEAN  COMMENT 'True when member_count is between 50 and 200 and avg_risk_score is above 1.0. These communities show anomalous size and centrality consistent with tight transfer rings.',
    top_account_id         BIGINT   COMMENT 'The account with the highest similarity_score in this community, ties broken by risk_score descending then account_id ascending. Identifies the most structurally similar account rather than the most transfer-central one.',
    total_volume_usd       DOUBLE   COMMENT 'Total account-to-account transfer volume in USD for links whose source and destination are both members of this community',
    topology               STRING   COMMENT 'Within-community transfer topology classification. Values: star, mesh, or chain',
    anchor_merchant_categories ARRAY<STRING> COMMENT 'Ground-truth anchor merchant categories for the fraud ring mapped to this community, in source order. Null for communities not mapped to a ground-truth ring.'
)
USING DELTA
COMMENT 'Louvain community summary — one row per community, pre-aggregated for ring-level analysis';
