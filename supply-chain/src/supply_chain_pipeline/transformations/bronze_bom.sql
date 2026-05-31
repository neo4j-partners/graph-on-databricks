-- Bronze: Raw Bill of Materials (parent-child part relationships) from landing volume.

CREATE OR REFRESH STREAMING TABLE bronze_bom
COMMENT 'Raw Bill of Materials records defining parent-child part relationships.'
CLUSTER BY (parent_part_id)
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed'       = 'true'
)
AS
SELECT
  *,
  current_timestamp()      AS _ingested_at,
  _metadata.file_path      AS _source_file
FROM STREAM read_files(
  '${volume_path}/bom/',
  format => 'parquet'
);
