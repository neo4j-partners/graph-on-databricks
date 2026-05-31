-- Gold: Two-level BOM explosion with rolled-up cost.
-- Flattens the parent→child hierarchy up to 2 levels deep and computes
-- total component cost per assembly. Used by the graph agent to project
-- the BOM sub-graph into Neo4j and answer "what parts are needed to build X?"

CREATE OR REFRESH MATERIALIZED VIEW gold_bom_explosion
COMMENT 'Two-level BOM explosion: each row is a (top-level assembly → leaf component) path with rolled-up cost and cumulative quantity.'
CLUSTER BY (top_parent_part_id)
AS
WITH
-- Level 1: direct parent → child relationships (active only)
level1 AS (
  SELECT
    b.bom_id         AS l1_bom_id,
    b.parent_part_id AS top_parent_part_id,
    b.child_part_id  AS l1_child_part_id,
    b.quantity       AS l1_quantity,
    1                AS depth
  FROM silver_bom b
  WHERE b.is_active = TRUE
),
-- Level 2: grandparent → grandchild (parent's children's children)
level2 AS (
  SELECT
    l1.top_parent_part_id,
    l1.l1_child_part_id  AS l1_child_part_id,
    b2.child_part_id     AS l2_child_part_id,
    l1.l1_quantity       AS l1_quantity,
    b2.quantity          AS l2_quantity,
    -- Cumulative quantity: how many leaf parts needed per 1 top-level assembly
    l1.l1_quantity * b2.quantity AS cumulative_quantity,
    2                    AS depth
  FROM level1 l1
  JOIN silver_bom b2
    ON l1.l1_child_part_id = b2.parent_part_id
   AND b2.is_active = TRUE
   AND b2.child_part_id != l1.top_parent_part_id  -- prevent back-references
)
-- Level 1 direct components
SELECT
  l1.top_parent_part_id,
  pp.part_name                            AS top_parent_name,
  pp.category                             AS top_parent_category,
  l1.l1_child_part_id                     AS component_part_id,
  cp.part_name                            AS component_name,
  cp.category                             AS component_category,
  cp.subcategory                          AS component_subcategory,
  cp.unit_cost_usd                        AS component_unit_cost_usd,
  cp.lead_time_days                       AS component_lead_time_days,
  cp.is_critical                          AS component_is_critical,
  l1.l1_quantity                          AS quantity_per_parent,
  l1.l1_quantity                          AS cumulative_quantity,
  l1.depth,
  ROUND(l1.l1_quantity * cp.unit_cost_usd, 4) AS rolled_up_cost_usd,
  NULL                                    AS via_part_id,
  NULL                                    AS via_part_name,
  CURRENT_TIMESTAMP()                     AS _computed_at
FROM level1 l1
JOIN silver_parts pp ON l1.top_parent_part_id = pp.part_id
JOIN silver_parts cp ON l1.l1_child_part_id   = cp.part_id

UNION ALL

-- Level 2 indirect components (through intermediate sub-assembly)
SELECT
  l2.top_parent_part_id,
  pp.part_name                            AS top_parent_name,
  pp.category                             AS top_parent_category,
  l2.l2_child_part_id                     AS component_part_id,
  cp.part_name                            AS component_name,
  cp.category                             AS component_category,
  cp.subcategory                          AS component_subcategory,
  cp.unit_cost_usd                        AS component_unit_cost_usd,
  cp.lead_time_days                       AS component_lead_time_days,
  cp.is_critical                          AS component_is_critical,
  l2.l2_quantity                          AS quantity_per_parent,
  l2.cumulative_quantity,
  l2.depth,
  ROUND(l2.cumulative_quantity * cp.unit_cost_usd, 4) AS rolled_up_cost_usd,
  l2.l1_child_part_id                     AS via_part_id,
  ip.part_name                            AS via_part_name,
  CURRENT_TIMESTAMP()                     AS _computed_at
FROM level2 l2
JOIN silver_parts pp ON l2.top_parent_part_id = pp.part_id
JOIN silver_parts cp ON l2.l2_child_part_id   = cp.part_id
JOIN silver_parts ip ON l2.l1_child_part_id   = ip.part_id;
