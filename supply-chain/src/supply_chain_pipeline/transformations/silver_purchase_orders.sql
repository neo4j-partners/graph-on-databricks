-- Silver: Cleaned and validated purchase orders with canonical status values.

CREATE OR REFRESH STREAMING TABLE silver_purchase_orders (
  po_id                    STRING       COMMENT 'Unique purchase order identifier (PO-XXXXXXX)',
  facility_id              STRING       COMMENT 'FK to silver_facilities — ordering facility',
  supplier_id              STRING       COMMENT 'FK to silver_suppliers — fulfilling supplier',
  part_id                  STRING       COMMENT 'FK to silver_parts — part being ordered',
  quantity                 INT          COMMENT 'Number of units ordered',
  unit_price_usd           DECIMAL(12,2) COMMENT 'Agreed unit price at time of order in USD',
  total_value_usd          DECIMAL(18,2) COMMENT 'Total order value (quantity × unit_price_usd)',
  order_date               DATE         COMMENT 'Date the purchase order was placed',
  expected_delivery_date   DATE         COMMENT 'Contractually expected delivery date',
  actual_delivery_date     DATE         COMMENT 'Actual delivery date; NULL if not yet delivered',
  status                   STRING       COMMENT 'PO lifecycle status: Open, In-Transit, Received, Delayed, Cancelled',
  priority                 STRING       COMMENT 'Business priority: Critical, High, Medium, Low',
  _ingested_at             TIMESTAMP    COMMENT 'Timestamp when the record was ingested at the bronze layer',
  CONSTRAINT pk_po              EXPECT (po_id IS NOT NULL)                                                  ON VIOLATION DROP ROW,
  CONSTRAINT fk_facility        EXPECT (facility_id IS NOT NULL)                                            ON VIOLATION DROP ROW,
  CONSTRAINT fk_supplier        EXPECT (supplier_id IS NOT NULL)                                            ON VIOLATION DROP ROW,
  CONSTRAINT fk_part            EXPECT (part_id IS NOT NULL)                                                ON VIOLATION DROP ROW,
  CONSTRAINT positive_qty       EXPECT (quantity > 0)                                                       ON VIOLATION DROP ROW,
  CONSTRAINT positive_price     EXPECT (unit_price_usd > 0)                                                 ON VIOLATION DROP ROW,
  CONSTRAINT valid_status       EXPECT (status IN ('Open','In-Transit','Received','Delayed','Cancelled'))   ON VIOLATION DROP ROW,
  CONSTRAINT valid_priority     EXPECT (priority IN ('Critical','High','Medium','Low'))                     ON VIOLATION DROP ROW,
  CONSTRAINT valid_date_order   EXPECT (expected_delivery_date >= order_date)                               ON VIOLATION DROP ROW
)
COMMENT 'Cleaned purchase orders with DQ constraints on status, priority, and date ordering.'
CLUSTER BY (order_date, status)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
SELECT
  po_id,
  facility_id,
  supplier_id,
  part_id,
  CAST(quantity              AS INT)           AS quantity,
  CAST(unit_price_usd        AS DECIMAL(12,2)) AS unit_price_usd,
  CAST(total_value_usd       AS DECIMAL(18,2)) AS total_value_usd,
  CAST(order_date            AS DATE)          AS order_date,
  CAST(expected_delivery_date AS DATE)         AS expected_delivery_date,
  CAST(actual_delivery_date  AS DATE)          AS actual_delivery_date,
  status,
  priority,
  _ingested_at
FROM STREAM bronze_purchase_orders
WHERE po_id IS NOT NULL
  AND facility_id IS NOT NULL
  AND supplier_id IS NOT NULL
  AND part_id IS NOT NULL;
