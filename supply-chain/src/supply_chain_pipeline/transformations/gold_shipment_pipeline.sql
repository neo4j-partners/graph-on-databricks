-- Gold: In-flight and delayed shipment pipeline.
-- Provides a real-time view of shipments currently in transit or delayed,
-- enriched with carrier, route, ETA, and associated PO context.
-- Used by the graph agent to build supplier→facility edges with latency weights.

CREATE OR REFRESH MATERIALIZED VIEW gold_shipment_pipeline
COMMENT 'In-transit and delayed shipments enriched with route, ETA, carrier, and PO context. Primary source for supply chain disruption detection.'
CLUSTER BY (status, carrier)
AS
SELECT
  sh.shipment_id,
  sh.po_id,
  sh.supplier_id,
  sup.supplier_name,
  sup.country                                                         AS supplier_country,
  sup.tier                                                            AS supplier_tier,
  sh.facility_id,
  fac.facility_name,
  fac.region                                                          AS destination_region,
  sh.part_id,
  p.part_name,
  p.category,
  p.is_critical,
  sh.quantity_shipped,
  ROUND(sh.quantity_shipped * p.unit_cost_usd, 2)                     AS shipment_value_usd,
  sh.ship_date,
  sh.expected_arrival_date,
  sh.carrier,
  sh.tracking_number,
  sh.status,
  sh.delay_days,
  sh.freight_cost_usd,
  -- Days until expected arrival (negative = overdue)
  DATEDIFF(sh.expected_arrival_date, CURRENT_DATE())                  AS days_until_eta,
  -- Transit duration in days
  DATEDIFF(sh.expected_arrival_date, sh.ship_date)                    AS transit_duration_days,
  -- Disruption severity for graph edge weighting
  CASE
    WHEN sh.status = 'Lost'                                THEN 'Severe'
    WHEN sh.status = 'Delayed' AND sh.delay_days > 14     THEN 'High'
    WHEN sh.status = 'Delayed' AND sh.delay_days > 7      THEN 'Medium'
    WHEN sh.status = 'Delayed'                            THEN 'Low'
    WHEN DATEDIFF(sh.expected_arrival_date, CURRENT_DATE()) < 0 THEN 'At Risk'
    ELSE                                                       'On Track'
  END                                                                 AS disruption_severity,
  -- Route key for graph edge identification
  CONCAT(sh.supplier_id, '->', sh.facility_id)                        AS route_key,
  CURRENT_TIMESTAMP()                                                 AS _computed_at
FROM silver_shipments sh
JOIN silver_suppliers  sup ON sh.supplier_id = sup.supplier_id
JOIN silver_facilities fac ON sh.facility_id = fac.facility_id
JOIN silver_parts      p   ON sh.part_id     = p.part_id
WHERE sh.status IN ('In-Transit','Delayed','Lost');
