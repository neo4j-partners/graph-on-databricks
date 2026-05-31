-- Silver: Cleaned, typed, and validated parts/components catalog.

CREATE OR REFRESH STREAMING TABLE silver_parts (
  part_id            STRING       COMMENT 'Unique part identifier (PRT-XXXXX)',
  part_name          STRING       COMMENT 'Descriptive name of the part or component',
  category           STRING       COMMENT 'Top-level category: Raw Material, Sub-Assembly, or Component',
  subcategory        STRING       COMMENT 'Second-level classification within category',
  unit_cost_usd      DECIMAL(12,2) COMMENT 'Standard unit cost in USD',
  unit_of_measure    STRING       COMMENT 'Stocking unit: EA (each), KG, LB, or M',
  lead_time_days     INT          COMMENT 'Typical supplier lead time in calendar days',
  min_order_qty      INT          COMMENT 'Minimum order quantity per purchase order',
  weight_kg          DECIMAL(8,2) COMMENT 'Unit weight in kilograms',
  is_critical        BOOLEAN      COMMENT 'True if part is on the critical path (no substitute available)',
  _ingested_at       TIMESTAMP    COMMENT 'Timestamp when the record was ingested at the bronze layer',
  CONSTRAINT pk_part          EXPECT (part_id IS NOT NULL)                              ON VIOLATION DROP ROW,
  CONSTRAINT valid_category   EXPECT (category IN ('Raw Material','Sub-Assembly','Component')) ON VIOLATION DROP ROW,
  CONSTRAINT positive_cost    EXPECT (unit_cost_usd > 0)                                ON VIOLATION DROP ROW,
  CONSTRAINT positive_lead    EXPECT (lead_time_days > 0)                               ON VIOLATION DROP ROW,
  CONSTRAINT positive_moq     EXPECT (min_order_qty > 0)                                ON VIOLATION DROP ROW
)
COMMENT 'Cleaned and validated parts/components catalog with quality constraints.'
CLUSTER BY (category, subcategory)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
SELECT
  part_id,
  part_name,
  category,
  subcategory,
  CAST(unit_cost_usd   AS DECIMAL(12,2)) AS unit_cost_usd,
  unit_of_measure,
  CAST(lead_time_days  AS INT)           AS lead_time_days,
  CAST(min_order_qty   AS INT)           AS min_order_qty,
  CAST(weight_kg       AS DECIMAL(8,2))  AS weight_kg,
  CAST(is_critical     AS BOOLEAN)       AS is_critical,
  _ingested_at
FROM STREAM bronze_parts
WHERE part_id IS NOT NULL;
