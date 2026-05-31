-- Silver: Cleaned Bill of Materials with self-reference guard and type enforcement.

CREATE OR REFRESH STREAMING TABLE silver_bom (
  bom_id           STRING       COMMENT 'Unique BOM record identifier (BOM-XXXXX)',
  parent_part_id   STRING       COMMENT 'FK to silver_parts — the assembly that contains the child',
  child_part_id    STRING       COMMENT 'FK to silver_parts — the component consumed by the parent',
  quantity         DECIMAL(10,3) COMMENT 'Quantity of child part required per one unit of parent',
  unit_of_measure  STRING       COMMENT 'Unit of measure for the quantity (typically EA)',
  effective_date   DATE         COMMENT 'Date from which this BOM relationship is valid',
  is_active        BOOLEAN      COMMENT 'False indicates a superseded or obsolete BOM record',
  _ingested_at     TIMESTAMP    COMMENT 'Timestamp when the record was ingested at the bronze layer',
  CONSTRAINT pk_bom          EXPECT (bom_id IS NOT NULL)                           ON VIOLATION DROP ROW,
  CONSTRAINT no_self_ref     EXPECT (parent_part_id != child_part_id)              ON VIOLATION DROP ROW,
  CONSTRAINT fk_parent       EXPECT (parent_part_id IS NOT NULL)                   ON VIOLATION DROP ROW,
  CONSTRAINT fk_child        EXPECT (child_part_id IS NOT NULL)                    ON VIOLATION DROP ROW,
  CONSTRAINT positive_qty    EXPECT (quantity > 0)                                 ON VIOLATION DROP ROW
)
COMMENT 'Validated Bill of Materials — parent-child part relationships with quantity and effectivity.'
CLUSTER BY (parent_part_id)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
SELECT
  bom_id,
  parent_part_id,
  child_part_id,
  CAST(quantity        AS DECIMAL(10,3)) AS quantity,
  unit_of_measure,
  CAST(effective_date  AS DATE)          AS effective_date,
  CAST(is_active       AS BOOLEAN)       AS is_active,
  _ingested_at
FROM STREAM bronze_bom
WHERE bom_id IS NOT NULL
  AND parent_part_id != child_part_id;
