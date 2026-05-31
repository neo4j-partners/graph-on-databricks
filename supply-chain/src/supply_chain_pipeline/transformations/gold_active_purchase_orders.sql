-- Gold: Active (open + delayed) purchase orders with aging buckets.
-- Used by the SQL agent for "what POs are at risk?" queries and by the
-- graph agent to identify bottleneck supplier→facility edges.

CREATE OR REFRESH MATERIALIZED VIEW gold_active_purchase_orders
COMMENT 'Open and delayed purchase orders enriched with aging buckets, supplier risk tier, and overdue flags.'
CLUSTER BY (status, aging_bucket)
AS
WITH active_pos AS (
  SELECT
    po.po_id,
    po.facility_id,
    po.supplier_id,
    po.part_id,
    po.quantity,
    po.unit_price_usd,
    po.total_value_usd,
    po.order_date,
    po.expected_delivery_date,
    po.status,
    po.priority,
    DATEDIFF(CURRENT_DATE(), po.order_date)                         AS age_days,
    DATEDIFF(CURRENT_DATE(), po.expected_delivery_date)             AS days_overdue,
    po.expected_delivery_date < CURRENT_DATE()                      AS is_overdue
  FROM silver_purchase_orders po
  WHERE po.status IN ('Open','In-Transit','Delayed')
)
SELECT
  ap.po_id,
  ap.facility_id,
  f.facility_name,
  f.region,
  ap.supplier_id,
  s.supplier_name,
  s.tier                                                            AS supplier_tier,
  s.country                                                         AS supplier_country,
  ap.part_id,
  p.part_name,
  p.category,
  p.is_critical,
  ap.quantity,
  ap.unit_price_usd,
  ap.total_value_usd,
  ap.order_date,
  ap.expected_delivery_date,
  ap.status,
  ap.priority,
  ap.age_days,
  ap.days_overdue,
  ap.is_overdue,
  -- Aging bucket for dashboard bucketing and graph edge weighting
  CASE
    WHEN ap.age_days <= 30  THEN '0-30 days'
    WHEN ap.age_days <= 60  THEN '31-60 days'
    WHEN ap.age_days <= 90  THEN '61-90 days'
    ELSE                         '90+ days'
  END                                                               AS aging_bucket,
  -- Exposure score for prioritisation (value × criticality × overdue weight)
  ROUND(
    ap.total_value_usd
    * CASE WHEN p.is_critical THEN 2.0 ELSE 1.0 END
    * CASE WHEN ap.is_overdue THEN 1.5 ELSE 1.0 END,
    2
  )                                                                 AS exposure_score,
  CURRENT_TIMESTAMP()                                               AS _computed_at
FROM active_pos ap
JOIN silver_suppliers  s ON ap.supplier_id  = s.supplier_id
JOIN silver_facilities f ON ap.facility_id  = f.facility_id
JOIN silver_parts      p ON ap.part_id      = p.part_id;
