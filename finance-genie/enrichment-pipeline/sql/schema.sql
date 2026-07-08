-- Base (silver) table schema for the graph-enriched finance pipeline.
--
-- Defines all six base tables with Unity Catalog column-level comments.
-- Column descriptions are the primary signal Genie uses to understand data.
--
-- Executed by upload_and_create_tables.sh before CSV data is loaded.
-- Placeholders ${catalog} and ${schema} are substituted by the shell script.
-- ${catalog} resolves to the silver catalog (SILVER_CATALOG, falling back to
-- the legacy single CATALOG when SILVER_CATALOG is unset).
--
-- To run manually in the Databricks SQL editor, replace placeholders:
--   ${catalog} → graph-enriched-finance-silver
--   ${schema}  → graph-enriched-schema

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.accounts (
    account_id   BIGINT  NOT NULL COMMENT 'Unique account identifier (primary key)',
    account_hash STRING           COMMENT 'Anonymized account identifier derived from the original account number',
    account_name STRING           COMMENT 'Account holder name: a person name for checking/savings accounts, a company name for business accounts',
    account_type STRING           COMMENT 'Account category: checking, savings, or business',
    region       STRING           COMMENT 'Geographic region where the account was opened',
    balance      DOUBLE           COMMENT 'Current account balance in USD',
    opened_date  DATE             COMMENT 'Date the account was opened',
    holder_age   INT              COMMENT 'Age of the account holder in years',
    CONSTRAINT accounts_pk PRIMARY KEY (account_id) RELY
)
USING DELTA
COMMENT 'Account dimension — one row per account holder';

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.customers (
    customer_id   BIGINT  NOT NULL COMMENT 'Unique customer identifier (primary key)',
    account_id    BIGINT           COMMENT 'Account owned by this customer (foreign key to accounts.account_id)',
    customer_name STRING           COMMENT 'Customer full name; matches the holder name on the linked account',
    phone         STRING           COMMENT 'Customer contact phone number in NANP format (e.g. 312-555-0142)',
    email         STRING           COMMENT 'Customer contact email address',
    address       STRING           COMMENT 'Customer mailing address as a single string: street, city, state and zip',
    CONSTRAINT customers_pk PRIMARY KEY (customer_id) RELY
)
USING DELTA
COMMENT 'Customer KYC identity dimension — one row per customer. Customers that share a phone number or address are a synthetic-identity risk signal';

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.merchants (
    merchant_id   BIGINT  NOT NULL COMMENT 'Unique merchant identifier (primary key)',
    merchant_name STRING           COMMENT 'Merchant business name',
    category      STRING           COMMENT 'Merchant business category (e.g., retail, food, entertainment)',
    region        STRING           COMMENT 'Geographic region where the merchant operates',
    CONSTRAINT merchants_pk PRIMARY KEY (merchant_id) RELY
)
USING DELTA
COMMENT 'Merchant dimension — one row per merchant';

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.transactions (
    txn_id        BIGINT     NOT NULL COMMENT 'Unique transaction identifier (primary key)',
    account_id    BIGINT              COMMENT 'Account that initiated the payment (foreign key to accounts.account_id)',
    merchant_id   BIGINT              COMMENT 'Merchant that received the payment (foreign key to merchants.merchant_id)',
    amount        DOUBLE              COMMENT 'Transaction amount in USD',
    txn_timestamp TIMESTAMP           COMMENT 'Timestamp when the transaction occurred',
    txn_hour      INT                 COMMENT 'Hour of day (0-23) when the transaction occurred',
    CONSTRAINT transactions_pk PRIMARY KEY (txn_id) RELY
)
USING DELTA
COMMENT 'Transaction fact table — one row per account-to-merchant payment event';

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.account_links (
    link_id            BIGINT     NOT NULL COMMENT 'Unique transfer event identifier (primary key)',
    src_account_id     BIGINT              COMMENT 'Account that sent the transfer (foreign key to accounts.account_id)',
    dst_account_id     BIGINT              COMMENT 'Account that received the transfer (foreign key to accounts.account_id)',
    amount             DOUBLE              COMMENT 'Transfer amount in USD',
    transfer_timestamp TIMESTAMP           COMMENT 'Timestamp when the transfer occurred',
    CONSTRAINT account_links_pk PRIMARY KEY (link_id) RELY
)
USING DELTA
COMMENT 'Account-to-account transfer graph — one row per directed transfer event';

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.account_labels (
    account_id BIGINT  NOT NULL COMMENT 'Account identifier (foreign key to accounts.account_id)',
    is_fraud   BOOLEAN          COMMENT 'Ground-truth fraud label: true if the account is a confirmed fraud ring member',
    CONSTRAINT account_labels_pk PRIMARY KEY (account_id) RELY
)
USING DELTA
COMMENT 'Ground-truth fraud labels — one row per account';

-- Informational FOREIGN KEY constraints (RELY). Added after all tables exist
-- so the CREATE OR REPLACE statements above stay free of cross-table
-- reference ordering. Unity Catalog does not enforce these; they are the
-- declared-relationship signal consumed by downstream tooling.
ALTER TABLE `${catalog}`.`${schema}`.customers
    ADD CONSTRAINT customers_account_fk FOREIGN KEY (account_id)
    REFERENCES `${catalog}`.`${schema}`.accounts (account_id) RELY;

ALTER TABLE `${catalog}`.`${schema}`.transactions
    ADD CONSTRAINT transactions_account_fk FOREIGN KEY (account_id)
    REFERENCES `${catalog}`.`${schema}`.accounts (account_id) RELY;

ALTER TABLE `${catalog}`.`${schema}`.transactions
    ADD CONSTRAINT transactions_merchant_fk FOREIGN KEY (merchant_id)
    REFERENCES `${catalog}`.`${schema}`.merchants (merchant_id) RELY;

ALTER TABLE `${catalog}`.`${schema}`.account_links
    ADD CONSTRAINT account_links_src_fk FOREIGN KEY (src_account_id)
    REFERENCES `${catalog}`.`${schema}`.accounts (account_id) RELY;

ALTER TABLE `${catalog}`.`${schema}`.account_links
    ADD CONSTRAINT account_links_dst_fk FOREIGN KEY (dst_account_id)
    REFERENCES `${catalog}`.`${schema}`.accounts (account_id) RELY;

ALTER TABLE `${catalog}`.`${schema}`.account_labels
    ADD CONSTRAINT account_labels_account_fk FOREIGN KEY (account_id)
    REFERENCES `${catalog}`.`${schema}`.accounts (account_id) RELY;
