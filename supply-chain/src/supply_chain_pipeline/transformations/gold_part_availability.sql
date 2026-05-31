-- Gold: Part availability by facility.
-- Computes ordered vs received quantities per part per facility to derive
-- a net_available_units figure and stock_status flag used by the graph
-- agent when answering inventory and shortage queries.

CREATE OR REFRESH MATERIALIZED VIEW gold_part_availability
COMMENT 'Net part availability per facility: ordered vs received quantities with stock status classification.'
CLUSTER BY (facility_id, stock_status)
AS
WITH ordered AS (
  SELECT
    po.facility_id,
    po.part_id,
    SUM(CASE WHEN po.status NOT IN ('Cancelled')
             THEN po.quantity ELSE 0 END)                AS total_ordered_units,
    SUM(CASE WHEN po.status = 'Received'
             THEN po.quantity ELSE 0 END)                AS total_received_units,
    SUM(CASE WHEN po.status IN ('Open','In-Transit','Delayed')
             THEN po.quantity ELSE 0 END)                AS in_pipeline_units,
    SUM(CASE WHEN po.status NOT IN ('Cancelled')
             THEN po.total_value_usd ELSE 0 END)         AS total_spend_usd,
    COUNT(DISTINCT po.supplier_id)                       AS distinct_suppliers,
    MAX(po.actual_delivery_date)                         AS last_receipt_date,
    MIN(CASE WHEN po.status IN ('Open','In-Transit','Delayed')
             THEN po.expected_delivery_date END)         AS next_expected_delivery
  FROM silver_purchase_orders po
  GROUP BY po.facility_id, po.part_id
),
in_transit_shipments AS (
  SELECT
    facility_id,
    part_id,
    SUM(quantity_shipped)                                AS qty_in_transit
  FROM silver_shipments
  WHERE status = 'In-Transit'
  GROUP BY facility_id, part_id
)
SELECT
  o.facility_id,
  f.facility_name,
  f.facility_type,
  f.region,
  o.part_id,
  p.part_name,
  p.category,
  p.subcategory,
  p.unit_cost_usd,
  p.is_critical,
  p.lead_time_days                                       AS supplier_lead_time_days,
  o.total_ordered_units,
  o.total_received_units,
  o.in_pipeline_units,
  COALESCE(t.qty_in_transit, 0)                         AS qty_in_transit_shipments,
  o.distinct_suppliers,
  o.total_spend_usd,
  o.last_receipt_date,
  o.next_expected_delivery,
  -- Stock status derived from pipeline coverage
  CASE
    WHEN o.total_received_units = 0 AND o.in_pipeline_units = 0 THEN 'Out of Stock'
    WHEN o.total_received_units = 0                              THEN 'Pending First Receipt'
    WHEN o.in_pipeline_units = 0                                 THEN 'Fully Received'
    WHEN o.in_pipeline_units * 1.0 / NULLIF(o.total_ordered_units, 0) > 0.5 THEN 'Partially Received'
    ELSE 'Mostly Received'
  END                                                    AS stock_status,
  CURRENT_TIMESTAMP()                                    AS _computed_at
FROM ordered o
JOIN silver_parts      p ON o.part_id      = p.part_id
JOIN silver_facilities f ON o.facility_id  = f.facility_id
LEFT JOIN in_transit_shipments t
  ON o.facility_id = t.facility_id AND o.part_id = t.part_id;
