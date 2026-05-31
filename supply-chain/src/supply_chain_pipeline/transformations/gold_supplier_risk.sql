-- Gold: Supplier risk assessment.
-- Aggregates PO delay rates and shipment on-time performance against each supplier's
-- baseline reliability_score to produce a composite risk_score (0–100, lower = safer)
-- and a categorical risk_tier used for graph node scoring and dashboard alerting.

CREATE OR REFRESH MATERIALIZED VIEW gold_supplier_risk
COMMENT 'Composite supplier risk score combining reliability, PO delay rate, and shipment on-time %. Refreshes automatically when silver sources change.'
CLUSTER BY (risk_tier, country)
AS
WITH po_metrics AS (
  SELECT
    supplier_id,
    COUNT(*)                                                           AS total_pos,
    SUM(CASE WHEN status IN ('Delayed','Cancelled') THEN 1 ELSE 0 END) AS problematic_pos,
    SUM(total_value_usd)                                               AS total_po_value_usd,
    AVG(CASE WHEN status = 'Delayed'
             THEN DATEDIFF(COALESCE(actual_delivery_date, CURRENT_DATE()), expected_delivery_date)
             ELSE 0 END)                                               AS avg_delay_days_on_delayed
  FROM silver_purchase_orders
  GROUP BY supplier_id
),
shipment_metrics AS (
  SELECT
    supplier_id,
    COUNT(*)                                                           AS total_shipments,
    SUM(CASE WHEN status = 'Delivered' THEN 1 ELSE 0 END)             AS on_time_shipments,
    SUM(CASE WHEN status IN ('Delayed','Lost') THEN 1 ELSE 0 END)     AS problem_shipments,
    AVG(delay_days)                                                    AS avg_delay_days
  FROM silver_shipments
  GROUP BY supplier_id
),
risk_calc AS (
  SELECT
    s.supplier_id,
    s.supplier_name,
    s.country,
    s.tier,
    s.reliability_score,
    s.certifications,
    s.payment_terms_days,
    COALESCE(p.total_pos, 0)                                           AS total_pos,
    COALESCE(p.total_po_value_usd, 0)                                  AS total_po_value_usd,
    COALESCE(p.problematic_pos, 0)                                     AS problematic_pos,
    ROUND(COALESCE(p.problematic_pos, 0) * 100.0
          / NULLIF(p.total_pos, 0), 1)                                 AS po_problem_rate_pct,
    COALESCE(sh.total_shipments, 0)                                    AS total_shipments,
    COALESCE(sh.on_time_shipments, 0)                                  AS on_time_shipments,
    ROUND(COALESCE(sh.on_time_shipments, 0) * 100.0
          / NULLIF(sh.total_shipments, 0), 1)                          AS shipment_on_time_pct,
    ROUND(COALESCE(sh.avg_delay_days, 0), 1)                           AS avg_shipment_delay_days,
    -- Composite risk score: 0 = perfect, 100 = critical
    -- Weights: reliability baseline 40%, PO problem rate 35%, shipment issues 25%
    ROUND(
      (1.0 - s.reliability_score) * 40.0
      + COALESCE(p.problematic_pos * 1.0 / NULLIF(p.total_pos, 0), 0) * 35.0
      + COALESCE(sh.problem_shipments * 1.0 / NULLIF(sh.total_shipments, 0), 0) * 25.0,
      2
    )                                                                  AS risk_score
  FROM silver_suppliers s
  LEFT JOIN po_metrics       p  ON s.supplier_id = p.supplier_id
  LEFT JOIN shipment_metrics sh ON s.supplier_id = sh.supplier_id
)
SELECT
  *,
  CASE
    WHEN risk_score < 10  THEN 'Low'
    WHEN risk_score < 25  THEN 'Medium'
    WHEN risk_score < 45  THEN 'High'
    ELSE                       'Critical'
  END AS risk_tier,
  CURRENT_TIMESTAMP() AS _computed_at
FROM risk_calc;
