-- Silver: Cleaned, typed, and validated supplier records.
-- Enforces referential integrity constraints and casts to canonical types.

CREATE OR REFRESH STREAMING TABLE silver_suppliers (
  supplier_id          STRING    COMMENT 'Unique supplier identifier (SUP-XXXXX)',
  supplier_name        STRING    COMMENT 'Legal company name of the supplier',
  country              STRING    COMMENT 'Country of supplier headquarters',
  city                 STRING    COMMENT 'City of supplier headquarters',
  tier                 STRING    COMMENT 'Procurement tier: Tier-1 (strategic), Tier-2, Tier-3',
  reliability_score    DECIMAL(4,3) COMMENT 'Historical delivery reliability score (0.0–1.0)',
  contact_email        STRING    COMMENT 'Primary procurement contact email',
  established_year     INT       COMMENT 'Year the supplier was founded',
  annual_revenue_usd   DECIMAL(18,2) COMMENT 'Latest annual revenue in USD',
  certifications       STRING    COMMENT 'Quality certifications held (e.g. ISO-9001, IATF-16949)',
  payment_terms_days   INT       COMMENT 'Standard payment terms in days (Net-15 to Net-90)',
  _ingested_at         TIMESTAMP COMMENT 'Timestamp when the record was ingested at the bronze layer',
  CONSTRAINT pk_supplier       EXPECT (supplier_id IS NOT NULL)                 ON VIOLATION DROP ROW,
  CONSTRAINT valid_tier        EXPECT (tier IN ('Tier-1','Tier-2','Tier-3'))     ON VIOLATION DROP ROW,
  CONSTRAINT valid_reliability EXPECT (reliability_score >= 0.0 AND reliability_score <= 1.0) ON VIOLATION DROP ROW,
  CONSTRAINT valid_revenue     EXPECT (annual_revenue_usd > 0)                  ON VIOLATION DROP ROW
)
COMMENT 'Cleaned and validated supplier master data with quality constraints.'
CLUSTER BY (country, tier)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
SELECT
  supplier_id,
  supplier_name,
  country,
  city,
  tier,
  CAST(reliability_score   AS DECIMAL(4,3)) AS reliability_score,
  contact_email,
  CAST(established_year    AS INT)          AS established_year,
  CAST(annual_revenue_usd  AS DECIMAL(18,2)) AS annual_revenue_usd,
  certifications,
  CAST(payment_terms_days  AS INT)          AS payment_terms_days,
  _ingested_at
FROM STREAM bronze_suppliers
WHERE supplier_id IS NOT NULL;
