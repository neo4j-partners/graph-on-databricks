-- Silver: Cleaned shipment records with status validation and type enforcement.

CREATE OR REFRESH STREAMING TABLE silver_shipments (
  shipment_id              STRING       COMMENT 'Unique shipment identifier (SHP-XXXXXXXX)',
  po_id                    STRING       COMMENT 'FK to silver_purchase_orders — the originating PO',
  supplier_id              STRING       COMMENT 'FK to silver_suppliers — shipping supplier',
  facility_id              STRING       COMMENT 'FK to silver_facilities — destination facility',
  part_id                  STRING       COMMENT 'FK to silver_parts — part being shipped',
  quantity_shipped         INT          COMMENT 'Number of units in this shipment (may be partial)',
  ship_date                DATE         COMMENT 'Date the shipment departed the supplier',
  expected_arrival_date    DATE         COMMENT 'Expected arrival date at destination facility',
  actual_arrival_date      DATE         COMMENT 'Actual arrival date; NULL if still in transit',
  carrier                  STRING       COMMENT 'Freight carrier name',
  tracking_number          STRING       COMMENT 'Carrier tracking number',
  status                   STRING       COMMENT 'Shipment status: In-Transit, Delivered, Delayed, Lost',
  delay_days               INT          COMMENT 'Number of days past expected arrival (0 if on-time)',
  freight_cost_usd         DECIMAL(10,2) COMMENT 'Total freight cost in USD',
  _ingested_at             TIMESTAMP    COMMENT 'Timestamp when the record was ingested at the bronze layer',
  CONSTRAINT pk_shipment        EXPECT (shipment_id IS NOT NULL)                                             ON VIOLATION DROP ROW,
  CONSTRAINT fk_po              EXPECT (po_id IS NOT NULL)                                                   ON VIOLATION DROP ROW,
  CONSTRAINT fk_supplier        EXPECT (supplier_id IS NOT NULL)                                             ON VIOLATION DROP ROW,
  CONSTRAINT fk_facility        EXPECT (facility_id IS NOT NULL)                                             ON VIOLATION DROP ROW,
  CONSTRAINT positive_qty       EXPECT (quantity_shipped > 0)                                                ON VIOLATION DROP ROW,
  CONSTRAINT valid_status       EXPECT (status IN ('In-Transit','Delivered','Delayed','Lost'))               ON VIOLATION DROP ROW,
  CONSTRAINT non_negative_delay EXPECT (delay_days >= 0)                                                     ON VIOLATION DROP ROW,
  CONSTRAINT valid_date_order   EXPECT (expected_arrival_date >= ship_date)                                  ON VIOLATION DROP ROW
)
COMMENT 'Cleaned shipment records with carrier, tracking, status validation, and delay measurement.'
CLUSTER BY (ship_date, status)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
SELECT
  shipment_id,
  po_id,
  supplier_id,
  facility_id,
  part_id,
  CAST(quantity_shipped       AS INT)           AS quantity_shipped,
  CAST(ship_date              AS DATE)          AS ship_date,
  CAST(expected_arrival_date  AS DATE)          AS expected_arrival_date,
  CAST(actual_arrival_date    AS DATE)          AS actual_arrival_date,
  carrier,
  tracking_number,
  status,
  CAST(delay_days             AS INT)           AS delay_days,
  CAST(freight_cost_usd       AS DECIMAL(10,2)) AS freight_cost_usd,
  _ingested_at
FROM STREAM bronze_shipments
WHERE shipment_id IS NOT NULL
  AND po_id IS NOT NULL;
